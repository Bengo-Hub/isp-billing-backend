"""Router agent polling endpoints.

These endpoints are called by MikroTik routers running the CodeVertex
polling agent script. Authentication is via X-Router-Token header
(per-router token generated during bootstrap), NOT via user JWT.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.router import Router
from app.models.router_command import CommandStatus, RouterCommand
from app.schemas.router_agent import (
    AgentPollRequest,
    AgentPollResponse,
    AgentReportRequest,
    AgentReportResponse,
    RouterAgentStatus,
    RouterCommandStatus,
)
from app.services.router_agent import RouterAgentService

logger = get_logger(__name__)

router = APIRouter()


async def _verify_router_token(
    router_id: int,
    x_router_token: str,
    db: AsyncSession,
) -> Router:
    """Verify the router agent token and return the router."""
    agent_service = RouterAgentService(db)
    is_valid = await agent_service.verify_agent_token(router_id, x_router_token)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid router agent token",
        )
    router_obj = await db.get(Router, router_id)
    if not router_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Router not found",
        )
    return router_obj


@router.post("/poll", response_model=AgentPollResponse)
async def agent_poll(
    request: AgentPollRequest,
    x_router_token: str = Header(..., alias="X-Router-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Router agent phones home with telemetry, receives pending commands.

    Called every ~30 seconds by the polling agent script on the MikroTik router.
    Authentication is via the X-Router-Token header (not user JWT).
    """
    await _verify_router_token(request.router_id, x_router_token, db)

    agent_service = RouterAgentService(db)
    result = await agent_service.handle_poll(
        router_id=request.router_id,
        telemetry=request.model_dump(exclude={"router_id"}),
    )
    return AgentPollResponse(**result)


@router.post("/poll-text")
async def agent_poll_text(
    request: AgentPollRequest,
    x_router_token: str = Header(..., alias="X-Router-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Router agent poll — returns pipe-delimited commands for RouterOS v6 parsing.

    Same as /poll but returns plain text instead of JSON, making it easier
    for RouterOS v6 scripts to parse (no native JSON parser on v6).

    Response format: action|param1|param2|...|command_id (one per line)
    """
    await _verify_router_token(request.router_id, x_router_token, db)

    agent_service = RouterAgentService(db)
    result = await agent_service.handle_poll(
        router_id=request.router_id,
        telemetry=request.model_dump(exclude={"router_id"}),
    )

    # Format as pipe-delimited text
    text_response = agent_service.format_commands_pipe_delimited(result["commands"])
    return Response(
        content=text_response,
        media_type="text/plain",
    )


@router.post("/report", response_model=AgentReportResponse)
async def agent_report(
    request: AgentReportRequest,
    x_router_token: str = Header(..., alias="X-Router-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Router agent reports command execution results.

    Called after the router executes commands received from the poll endpoint.
    """
    await _verify_router_token(request.router_id, x_router_token, db)

    agent_service = RouterAgentService(db)
    results_data = [r.model_dump() for r in request.results]
    await agent_service.handle_report(
        router_id=request.router_id,
        results=results_data,
    )

    return AgentReportResponse(ok=True, processed=len(request.results))


@router.get("/status/{router_id}", response_model=RouterAgentStatus)
async def get_agent_status(
    router_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get the polling agent status for a router.

    This endpoint is for the admin dashboard (uses normal auth via the
    router include, not agent token auth).
    """
    from app.core.config import settings
    from datetime import datetime

    router_obj = await db.get(Router, router_id)
    if not router_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Router not found",
        )

    # Count pending commands
    result = await db.execute(
        select(RouterCommand)
        .where(
            and_(
                RouterCommand.router_id == router_id,
                RouterCommand.status == CommandStatus.PENDING,
            )
        )
    )
    pending_count = len(result.scalars().all())

    # Determine if online based on last poll
    is_online = False
    if router_obj.last_poll_at:
        elapsed = (datetime.utcnow() - router_obj.last_poll_at).total_seconds()
        threshold = router_obj.agent_poll_interval * settings.agent_offline_threshold_multiplier
        is_online = elapsed < threshold

    return RouterAgentStatus(
        router_id=router_id,
        agent_installed=router_obj.agent_installed,
        agent_version=router_obj.agent_version,
        last_poll_at=router_obj.last_poll_at.isoformat() if router_obj.last_poll_at else None,
        poll_interval=router_obj.agent_poll_interval,
        is_online=is_online,
        pending_commands=pending_count,
    )


@router.get("/commands/{router_id}", response_model=list[RouterCommandStatus])
async def get_router_commands(
    router_id: int,
    status_filter: str = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Get recent commands for a router (admin dashboard)."""
    query = select(RouterCommand).where(RouterCommand.router_id == router_id)

    if status_filter:
        query = query.where(RouterCommand.status == status_filter)

    query = query.order_by(RouterCommand.created_at.desc()).limit(limit)
    result = await db.execute(query)
    commands = result.scalars().all()

    return [
        RouterCommandStatus(
            id=cmd.id,
            action=cmd.action,
            params=cmd.params,
            priority=cmd.priority,
            status=cmd.status,
            created_at=cmd.created_at.isoformat() if cmd.created_at else None,
            sent_at=cmd.sent_at.isoformat() if cmd.sent_at else None,
            completed_at=cmd.completed_at.isoformat() if cmd.completed_at else None,
            result_message=cmd.result_message,
            retry_count=cmd.retry_count,
            source=cmd.source,
        )
        for cmd in commands
    ]


@router.get("/script/{router_id}", response_class=PlainTextResponse)
async def get_agent_script(
    router_id: int,
    token: str = Query(..., description="Agent token for verification"),
    db: AsyncSession = Depends(get_db),
):
    """Generate the RouterOS polling agent installer script for a router.

    Downloaded by the bootstrap script via /tool/fetch, then /import'd.
    This script creates the codevertex-agent system script and scheduler.

    Auth: uses the agent token (not user JWT) since this is called from the router.
    """
    agent_service = RouterAgentService(db)
    is_valid = await agent_service.verify_agent_token(router_id, token)
    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid agent token")

    router_obj = await db.get(Router, router_id)
    if not router_obj:
        raise HTTPException(status_code=404, detail="Router not found")

    # Build URLs
    backend_url = settings.backend_url or ""
    poll_url = f"{backend_url}/api/v1/router-agent/poll-text"
    report_url = f"{backend_url}/api/v1/router-agent/report"
    poll_interval = router_obj.agent_poll_interval or settings.agent_default_poll_interval
    agent_token_plain = router_obj.agent_token_plain or token

    # Generate the RouterOS script that will be /import'd
    # This script:
    #   1. Removes any existing agent script + scheduler
    #   2. Creates the polling agent script with embedded config
    #   3. Creates a scheduler to run it every N seconds
    script = _generate_routeros_agent_script(
        router_id=router_id,
        agent_token=agent_token_plain,
        poll_url=poll_url,
        report_url=report_url,
        poll_interval=poll_interval,
    )

    return script


def _generate_routeros_agent_script(
    router_id: int,
    agent_token: str,
    poll_url: str,
    report_url: str,
    poll_interval: int = 30,
) -> str:
    """Generate pure RouterOS script for the polling agent.

    This script is designed to be /import'd on the router.
    It creates the agent script and scheduler entries.

    The agent script itself:
    - Collects telemetry (CPU, memory, active sessions)
    - POSTs telemetry to the backend /poll-text endpoint
    - Receives pipe-delimited commands in the response
    - Executes each command (disconnect, disable_user, enable_user, create_user)
    - Reports results back to the backend /report endpoint

    Uses /tool/fetch with output=user as-value (works on RouterOS v6.43+ and all v7).
    Pipe-delimited response format avoids need for JSON parsing on v6.
    """
    return f"""# CodeVertex Billing Agent Installer
# Router ID: {router_id}
# Generated by CodeVertex ISP Billing System

:put "Installing CodeVertex billing agent..."
:log info "[AGENT] Installing CodeVertex billing agent..."

# Remove existing agent if present
:do {{ /system/scheduler/remove [find name="codevertex-agent"] }} on-error={{}}
:do {{ /system/script/remove [find name="codevertex-agent"] }} on-error={{}}

# Create the polling agent script
/system/script/add name="codevertex-agent" \\
  policy=ftp,reboot,read,write,policy,test,password,sniff,sensitive,api \\
  source="
# CodeVertex Billing Agent v{settings.agent_script_version}
# Polls backend every {poll_interval}s for commands

:local agentToken \\"{agent_token}\\"
:local pollUrl \\"{poll_url}\\"
:local reportUrl \\"{report_url}\\"
:local routerId {router_id}

# Collect telemetry
:local cpu [/system/resource/get cpu-load]
:local freeMem [/system/resource/get free-memory]
:local totalMem [/system/resource/get total-memory]
:local uptime [/system/resource/get uptime]
:local ver [/system/resource/get version]
:local activePppoe 0
:local activeHotspot 0
:do {{ :set activePppoe [:len [/ppp/active/find]] }} on-error={{}}
:do {{ :set activeHotspot [:len [/ip/hotspot/active/find]] }} on-error={{}}

# Build JSON payload
:local payload (\\"{{\\\\\\\"router_id\\\\\\\": \\" . \\$routerId . \\", \\\\\\\"version\\\\\\\": \\\\\\\"\\\" . \\$ver . \\"\\\\\\\"\\\" . \\", \\\\\\\"uptime\\\\\\\": \\\\\\\"\\\" . \\$uptime . \\"\\\\\\\"\\\" . \\", \\\\\\\"cpu_load\\\\\\\": \\" . \\$cpu . \\", \\\\\\\"free_memory\\\\\\\": \\" . \\$freeMem . \\", \\\\\\\"total_memory\\\\\\\": \\" . \\$totalMem . \\", \\\\\\\"active_pppoe\\\\\\\": \\" . \\$activePppoe . \\", \\\\\\\"active_hotspot\\\\\\\": \\" . \\$activeHotspot . \\"}}\\")

# Poll backend
:do {{
  :local result [/tool/fetch url=\\$pollUrl http-method=post \\
    http-header-field=\\"Content-Type:application/json,X-Router-Token:\\$agentToken\\" \\
    http-data=\\$payload output=user as-value]

  :if ((\\$result->\\"status\\") = \\"finished\\") do={{
    :local data (\\$result->\\"data\\")

    # Parse pipe-delimited commands
    :while ([:len \\$data] > 2) do={{
      :local lineEnd [:find \\$data \\"\\\\n\\"]
      :if ([:typeof \\$lineEnd] = \\"nil\\") do={{ :set lineEnd [:len \\$data] }}
      :local line [:pick \\$data 0 \\$lineEnd]
      :set data [:pick \\$data (\\$lineEnd + 1) [:len \\$data]]

      :if ([:len \\$line] > 2) do={{
        :local sep1 [:find \\$line \\"|\\"]
        :if ([:typeof \\$sep1] != \\"nil\\") do={{
          :local action [:pick \\$line 0 \\$sep1]
          :local rest [:pick \\$line (\\$sep1 + 1) [:len \\$line]]

          # --- DISCONNECT ---
          :if (\\$action = \\"disconnect\\") do={{
            :local sep2 [:find \\$rest \\"|\\"]
            :local uname [:pick \\$rest 0 \\$sep2]
            :local cid [:pick \\$rest (\\$sep2 + 1) [:len \\$rest]]
            :local cs \\"success\\"
            :local cm \\"\\"
            :do {{
              :do {{ /ppp/active/remove [find name=\\$uname] }} on-error={{}}
              :do {{ /ip/hotspot/active/remove [find user=\\$uname] }} on-error={{}}
            }} on-error={{ :set cs \\"failed\\"; :set cm \\"disconnect error\\" }}
            :do {{
              /tool/fetch url=\\$reportUrl http-method=post \\
                http-header-field=\\"Content-Type:application/json,X-Router-Token:\\$agentToken\\" \\
                http-data=(\\"{{\\\\\\\"router_id\\\\\\\":\\" . \\$routerId . \\",\\\\\\\"results\\\\\\\":[{{\\\\\\\"id\\\\\\\":\\\\\\\"\\" . \\$cid . \\"\\\\\\\",\\\\\\\"status\\\\\\\":\\\\\\\"\\" . \\$cs . \\"\\\\\\\",\\\\\\\"message\\\\\\\":\\\\\\\"\\" . \\$cm . \\"\\\\\\\"}}]}}\\" ) \\
                output=none
            }} on-error={{}}
          }}

          # --- DISABLE USER ---
          :if (\\$action = \\"disable_user\\") do={{
            :local sep2 [:find \\$rest \\"|\\"]
            :local sep3 [:find \\$rest \\"|\\" (\\$sep2 + 1)]
            :local uname [:pick \\$rest 0 \\$sep2]
            :local utype [:pick \\$rest (\\$sep2 + 1) \\$sep3]
            :local cid [:pick \\$rest (\\$sep3 + 1) [:len \\$rest]]
            :local cs \\"success\\"
            :local cm \\"\\"
            :do {{
              :if (\\$utype = \\"hotspot\\") do={{
                /ip/hotspot/user/set [find name=\\$uname] disabled=yes
                :do {{ /ip/hotspot/active/remove [find user=\\$uname] }} on-error={{}}
              }} else={{
                /ppp/secret/set [find name=\\$uname] disabled=yes
                :do {{ /ppp/active/remove [find name=\\$uname] }} on-error={{}}
              }}
            }} on-error={{ :set cs \\"failed\\"; :set cm \\"disable error\\" }}
            :do {{
              /tool/fetch url=\\$reportUrl http-method=post \\
                http-header-field=\\"Content-Type:application/json,X-Router-Token:\\$agentToken\\" \\
                http-data=(\\"{{\\\\\\\"router_id\\\\\\\":\\" . \\$routerId . \\",\\\\\\\"results\\\\\\\":[{{\\\\\\\"id\\\\\\\":\\\\\\\"\\" . \\$cid . \\"\\\\\\\",\\\\\\\"status\\\\\\\":\\\\\\\"\\" . \\$cs . \\"\\\\\\\",\\\\\\\"message\\\\\\\":\\\\\\\"\\" . \\$cm . \\"\\\\\\\"}}]}}\\" ) \\
                output=none
            }} on-error={{}}
          }}

          # --- ENABLE USER ---
          :if (\\$action = \\"enable_user\\") do={{
            :local sep2 [:find \\$rest \\"|\\"]
            :local sep3 [:find \\$rest \\"|\\" (\\$sep2 + 1)]
            :local uname [:pick \\$rest 0 \\$sep2]
            :local utype [:pick \\$rest (\\$sep2 + 1) \\$sep3]
            :local cid [:pick \\$rest (\\$sep3 + 1) [:len \\$rest]]
            :local cs \\"success\\"
            :local cm \\"\\"
            :do {{
              :if (\\$utype = \\"hotspot\\") do={{
                /ip/hotspot/user/set [find name=\\$uname] disabled=no
              }} else={{
                /ppp/secret/set [find name=\\$uname] disabled=no
              }}
            }} on-error={{ :set cs \\"failed\\"; :set cm \\"enable error\\" }}
            :do {{
              /tool/fetch url=\\$reportUrl http-method=post \\
                http-header-field=\\"Content-Type:application/json,X-Router-Token:\\$agentToken\\" \\
                http-data=(\\"{{\\\\\\\"router_id\\\\\\\":\\" . \\$routerId . \\",\\\\\\\"results\\\\\\\":[{{\\\\\\\"id\\\\\\\":\\\\\\\"\\" . \\$cid . \\"\\\\\\\",\\\\\\\"status\\\\\\\":\\\\\\\"\\" . \\$cs . \\"\\\\\\\",\\\\\\\"message\\\\\\\":\\\\\\\"\\" . \\$cm . \\"\\\\\\\"}}]}}\\" ) \\
                output=none
            }} on-error={{}}
          }}

          # --- CREATE USER ---
          :if (\\$action = \\"create_user\\") do={{
            :local sep2 [:find \\$rest \\"|\\"]
            :local sep3 [:find \\$rest \\"|\\" (\\$sep2 + 1)]
            :local sep4 [:find \\$rest \\"|\\" (\\$sep3 + 1)]
            :local sep5 [:find \\$rest \\"|\\" (\\$sep4 + 1)]
            :local sep6 [:find \\$rest \\"|\\" (\\$sep5 + 1)]
            :local uname [:pick \\$rest 0 \\$sep2]
            :local upass [:pick \\$rest (\\$sep2 + 1) \\$sep3]
            :local utype [:pick \\$rest (\\$sep3 + 1) \\$sep4]
            :local uprof [:pick \\$rest (\\$sep4 + 1) \\$sep5]
            :local urate [:pick \\$rest (\\$sep5 + 1) \\$sep6]
            :local cid [:pick \\$rest (\\$sep6 + 1) [:len \\$rest]]
            :local cs \\"success\\"
            :local cm \\"\\"
            :do {{
              :if (\\$utype = \\"hotspot\\") do={{
                :do {{ /ip/hotspot/user/remove [find name=\\$uname] }} on-error={{}}
                /ip/hotspot/user/add name=\\$uname password=\\$upass profile=\\$uprof
              }} else={{
                :do {{ /ppp/secret/remove [find name=\\$uname] }} on-error={{}}
                /ppp/secret/add name=\\$uname password=\\$upass profile=\\$uprof service=pppoe
              }}
            }} on-error={{ :set cs \\"failed\\"; :set cm \\"create error\\" }}
            :do {{
              /tool/fetch url=\\$reportUrl http-method=post \\
                http-header-field=\\"Content-Type:application/json,X-Router-Token:\\$agentToken\\" \\
                http-data=(\\"{{\\\\\\\"router_id\\\\\\\":\\" . \\$routerId . \\",\\\\\\\"results\\\\\\\":[{{\\\\\\\"id\\\\\\\":\\\\\\\"\\" . \\$cid . \\"\\\\\\\",\\\\\\\"status\\\\\\\":\\\\\\\"\\" . \\$cs . \\"\\\\\\\",\\\\\\\"message\\\\\\\":\\\\\\\"\\" . \\$cm . \\"\\\\\\\"}}]}}\\" ) \\
                output=none
            }} on-error={{}}
          }}
        }}
      }}
    }}
  }}
}} on-error={{
  :log warning \\"CodeVertex agent: poll failed\\"
}}
"

# Create scheduler to run agent every {poll_interval} seconds
/system/scheduler/add name="codevertex-agent" interval={poll_interval}s \\
  on-event="/system/script/run codevertex-agent" \\
  policy=ftp,reboot,read,write,policy,test,password,sniff,sensitive,api

:put "[OK] Billing agent installed (polling every {poll_interval}s)"
:log info "[AGENT] Billing agent installed successfully (v{settings.agent_script_version})"
"""
