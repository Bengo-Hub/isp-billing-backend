"""Router agent polling endpoints.

These endpoints are called by MikroTik routers running the CodeVertex
polling agent script. Authentication is via X-Router-Token header
(per-router token generated during bootstrap), NOT via user JWT.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
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


@router.post("/backup-upload/{router_id}")
async def agent_backup_upload(
    router_id: int,
    request: Request,
    token: str = Query(..., description="Per-router agent token"),
    backup_id: Optional[int] = Query(None, description="RouterBackup row id"),
    name: Optional[str] = Query(None, description="Backup file name on the router"),
    db: AsyncSession = Depends(get_db),
):
    """Receive a router .backup file uploaded NAT-safely by the polling agent.

    The agent runs ``/system/backup/save`` then ``/tool fetch upload`` to POST the
    file here. Auth is the per-router agent token in the query (the fetch upload
    can't set the X-Router-Token header). The request body is the raw .backup
    binary; it is stored on the matching RouterBackup row and flips it to
    completed so the platform can serve it for download.
    """
    from app.models.router import RouterBackup

    agent_service = RouterAgentService(db)
    if not await agent_service.verify_agent_token(router_id, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid router agent token",
        )

    body = await request.body()
    if not body:
        # Diagnostic ping from the router's on-error path (the file upload
        # failed) — log the context so the failure reason is visible
        # server-side instead of only in the router's local log.
        qp = request.query_params
        if qp.get("status") == "failed":
            logger.warning(
                f"Backup upload FAILED on router {router_id} "
                f"(backup_id={backup_id}, name={name}): "
                f"file_present={qp.get('file_present')} size={qp.get('size')}"
            )
            return {"ok": False, "diagnostic": "upload_failed"}
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty backup body",
        )

    backup = None
    if backup_id:
        backup = (
            await db.execute(
                select(RouterBackup).where(
                    and_(
                        RouterBackup.id == backup_id,
                        RouterBackup.router_id == router_id,
                    )
                )
            )
        ).scalar_one_or_none()
    if backup is None:
        # Fallback: newest backup row for this router (one-at-a-time in practice).
        backup = (
            await db.execute(
                select(RouterBackup)
                .where(RouterBackup.router_id == router_id)
                .order_by(RouterBackup.created_at.desc())
            )
        ).scalars().first()
    if backup is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No backup row to attach the file to",
        )

    backup.file_data = body
    backup.size_bytes = len(body)
    backup.status = "completed"
    backup.completed_at = datetime.utcnow()
    if name:
        backup.name = name
    await db.commit()
    logger.info(
        f"Stored backup file for router {router_id} "
        f"(backup {backup.id}, {len(body)} bytes)"
    )
    return {"ok": True, "backup_id": backup.id, "size": len(body)}


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
    seconds_since = None
    if router_obj.last_poll_at:
        elapsed = (datetime.utcnow() - router_obj.last_poll_at).total_seconds()
        seconds_since = int(elapsed)
        threshold = router_obj.agent_poll_interval * settings.agent_offline_threshold_multiplier
        is_online = elapsed < threshold

    # Recent command history (for the dashboard timeline)
    recent_res = await db.execute(
        select(RouterCommand)
        .where(RouterCommand.router_id == router_id)
        .order_by(RouterCommand.created_at.desc())
        .limit(10)
    )
    recent_commands = [
        {
            "id": cmd.id,
            "action": cmd.action,
            "status": cmd.status,
            "created_at": cmd.created_at.isoformat() if cmd.created_at else None,
        }
        for cmd in recent_res.scalars().all()
    ]

    return RouterAgentStatus(
        router_id=router_id,
        agent_installed=router_obj.agent_installed,
        agent_version=router_obj.agent_version,
        last_poll_at=router_obj.last_poll_at.isoformat() if router_obj.last_poll_at else None,
        poll_interval=router_obj.agent_poll_interval,
        is_online=is_online,
        pending_commands=pending_count,
        seconds_since_last_poll=seconds_since,
        recent_commands=recent_commands,
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
    mode: str = Query("installer", description="'installer' (default) installs the scheduler; 'body' returns the polling logic the scheduler imports each tick"),
    db: AsyncSession = Depends(get_db),
):
    """Generate the RouterOS polling agent script for a router.

    Downloaded by the bootstrap script via /tool/fetch, then /import'd.

    Two modes:
    - ``installer`` (default): a small script that downloads the agent *body*
      to ``cvagent.rsc`` and registers a ``/system/scheduler`` entry that
      ``/import``s it every N seconds. THIS is what makes the agent actually
      poll on a recurring basis (previously the endpoint only returned the body,
      so importing it ran a single poll and never scheduled anything).
    - ``body``: the actual polling logic (collect telemetry, POST /poll-text,
      execute pipe-delimited commands, POST /report). Fetched + imported by the
      scheduler on every tick.

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

    if mode == "body":
        # The polling logic imported by the scheduler on every tick.
        return _generate_routeros_agent_script(
            router_id=router_id,
            agent_token=agent_token_plain,
            poll_url=poll_url,
            report_url=report_url,
            poll_interval=poll_interval,
        )

    # Default: the installer that downloads the body + registers the scheduler.
    body_url = (
        f"{backend_url}/api/v1/router-agent/script/{router_id}"
        f"?token={agent_token_plain}&mode=body"
    )
    return _generate_agent_installer_script(
        router_id=router_id,
        body_url=body_url,
        poll_interval=poll_interval,
    )


def _generate_agent_installer_script(
    router_id: int,
    body_url: str,
    poll_interval: int = 30,
) -> str:
    """Generate the RouterOS installer that registers the recurring polling agent.

    Imported once by the bootstrap script. It:
      1. Removes any previous codevertex-agent scheduler + cached body file.
      2. Downloads the agent body to ``cvagent.rsc``.
      3. Creates a ``/system/scheduler`` entry that ``/import``s the body every
         ``poll_interval`` seconds (this is the recurring poll loop).
      4. Runs the body once immediately so the first poll happens right away.

    This is a top-level .rsc (NOT embedded in source="..."), so standard
    RouterOS syntax applies — only Python f-string braces are doubled.
    """
    return f"""# CodeVertex Billing Agent Installer
# Router ID: {router_id}
# Registers the polling agent scheduler (runs every {poll_interval}s).

:put "[CVAGENT] Installing CodeVertex polling agent..."

# Remove any previous agent scheduler + cached body file
:do {{ /system/scheduler/remove [find name="codevertex-agent"] }} on-error={{}}
:do {{ /file/remove [find name="cvagent.rsc"] }} on-error={{}}

# Download the agent body to a local file
:do {{
  /tool/fetch mode=https url="{body_url}" dst-path=cvagent.rsc
  :delay 2s
  :put "[CVAGENT] Agent body downloaded"
}} on-error={{ :put "[CVAGENT] ERROR: failed to download agent body" }}

# Create the recurring scheduler that imports the agent body every {poll_interval}s
:do {{
  /system/scheduler/add name="codevertex-agent" interval={poll_interval}s \\
    on-event="/import file-name=cvagent.rsc" \\
    policy=ftp,read,write,test,policy,sensitive \\
    comment="CodeVertex billing agent - DO NOT DELETE"
  :put "[CVAGENT] Scheduler created (every {poll_interval}s)"
}} on-error={{ :put "[CVAGENT] ERROR: failed to create scheduler" }}

# Run once immediately so the first poll happens now
:do {{ /import file-name=cvagent.rsc }} on-error={{ :put "[CVAGENT] First run will happen on next schedule tick" }}

:put "[CVAGENT] Install complete"
"""


def _generate_routeros_agent_script(
    router_id: int,
    agent_token: str,
    poll_url: str,
    report_url: str,
    poll_interval: int = 30,
) -> str:
    """Generate a standalone RouterOS script for the polling agent.

    This script is designed to be saved as a .rsc file on the router and
    executed every N seconds via /system/scheduler with on-event="/import ...".

    Because it's a top-level .rsc file (NOT embedded inside source="..."),
    no multi-level escaping is needed. Standard RouterOS syntax applies.

    The agent:
    - Collects telemetry (CPU, memory, active sessions)
    - POSTs telemetry to the backend /poll-text endpoint
    - Receives pipe-delimited commands in the response
    - Executes each command (disconnect, disable_user, enable_user, create_user)
    - Reports results back to the backend /report endpoint

    Uses /tool/fetch with output=user as-value (works on RouterOS v6.43+ and all v7).
    Pipe-delimited response format avoids need for JSON parsing on v6.
    """
    # Helper to generate the report-result fetch block for a command
    def _report_block():
        return '''  :do {
    /tool/fetch url=$reportUrl http-method=post \\
      http-header-field="Content-Type:application/json,X-Router-Token:$agentToken" \\
      http-data=("{\\"router_id\\":" . $routerId . ",\\"results\\":[{\\"id\\":\\"" . $cid . "\\",\\"status\\":\\"" . $cs . "\\",\\"message\\":\\"" . $cm . "\\"}]}") \\
      output=none
  } on-error={}'''

    report = _report_block()

    return f"""# CodeVertex Billing Agent v{settings.agent_script_version}
# Router ID: {router_id}
# This file is executed every {poll_interval}s by the codevertex-agent scheduler.
# Do not edit manually - regenerated by bootstrap.

:local agentToken "{agent_token}"
:local pollUrl "{poll_url}"
:local reportUrl "{report_url}"
:local routerId {router_id}

# Collect telemetry
:local cpu [/system/resource/get cpu-load]
:local freeMem [/system/resource/get free-memory]
:local totalMem [/system/resource/get total-memory]
:local uptime [/system/resource/get uptime]
:local ver [/system/resource/get version]
:local freeHdd 0
:local totalHdd 0
:do {{ :set freeHdd [/system/resource/get free-hdd-space] }} on-error={{}}
:do {{ :set totalHdd [/system/resource/get total-hdd-space] }} on-error={{}}
:local activePppoe 0
:local activeHotspot 0
:do {{ :set activePppoe [:len [/ppp/active/find]] }} on-error={{}}
:do {{ :set activeHotspot [:len [/ip/hotspot/active/find]] }} on-error={{}}

# Build the active-users JSON array (NAT-safe live data for the dashboard).
# Each element: {{"username","type","address","mac","uptime"}}.
:local users ""
:do {{
  :foreach h in=[/ip/hotspot/active/find] do={{
    :local hu [/ip/hotspot/active/get $h user]
    :local ha [/ip/hotspot/active/get $h address]
    :local hm ""
    :do {{ :set hm [/ip/hotspot/active/get $h mac-address] }} on-error={{}}
    :local ht ""
    :do {{ :set ht [/ip/hotspot/active/get $h uptime] }} on-error={{}}
    :if ([:len $users] > 0) do={{ :set users ($users . ",") }}
    :set users ($users . "{{\\\"username\\\":\\\"" . $hu . "\\\",\\\"type\\\":\\\"hotspot\\\",\\\"address\\\":\\\"" . $ha . "\\\",\\\"mac\\\":\\\"" . $hm . "\\\",\\\"uptime\\\":\\\"" . $ht . "\\\"}}")
  }}
}} on-error={{}}
:do {{
  :foreach p in=[/ppp/active/find] do={{
    :local pu [/ppp/active/get $p name]
    :local pa ""
    :do {{ :set pa [/ppp/active/get $p address] }} on-error={{}}
    :local pt ""
    :do {{ :set pt [/ppp/active/get $p uptime] }} on-error={{}}
    :if ([:len $users] > 0) do={{ :set users ($users . ",") }}
    :set users ($users . "{{\\\"username\\\":\\\"" . $pu . "\\\",\\\"type\\\":\\\"pppoe\\\",\\\"address\\\":\\\"" . $pa . "\\\",\\\"mac\\\":\\\"\\\",\\\"uptime\\\":\\\"" . $pt . "\\\"}}")
  }}
}} on-error={{}}

# Build JSON payload
:local payload ("{{\\\"router_id\\\": " . $routerId . ", \\\"version\\\": \\\"" . $ver . "\\\", \\\"uptime\\\": \\\"" . $uptime . "\\\", \\\"cpu_load\\\": " . $cpu . ", \\\"free_memory\\\": " . $freeMem . ", \\\"total_memory\\\": " . $totalMem . ", \\\"free_hdd_space\\\": " . $freeHdd . ", \\\"total_hdd_space\\\": " . $totalHdd . ", \\\"active_pppoe\\\": " . $activePppoe . ", \\\"active_hotspot\\\": " . $activeHotspot . ", \\\"active_users\\\": [" . $users . "]}}")

# Poll backend
:do {{
  :local result [/tool/fetch url=$pollUrl http-method=post \\
    http-header-field="Content-Type:application/json,X-Router-Token:$agentToken" \\
    http-data=$payload output=user as-value]

  :if (($result->"status") = "finished") do={{
    :local data ($result->"data")

    # Parse pipe-delimited commands (one per line: action|param1|...|cmd_id)
    :while ([:len $data] > 2) do={{
      :local lineEnd [:find $data "\\n"]
      :if ([:typeof $lineEnd] = "nil") do={{ :set lineEnd [:len $data] }}
      :local line [:pick $data 0 $lineEnd]
      :set data [:pick $data ($lineEnd + 1) [:len $data]]

      :if ([:len $line] > 2) do={{
        :local sep1 [:find $line "|"]
        :if ([:typeof $sep1] != "nil") do={{
          :local action [:pick $line 0 $sep1]
          :local rest [:pick $line ($sep1 + 1) [:len $line]]

          # --- DISCONNECT ---
          :if ($action = "disconnect") do={{
            :local sep2 [:find $rest "|"]
            :local uname [:pick $rest 0 $sep2]
            :local cid [:pick $rest ($sep2 + 1) [:len $rest]]
            :local cs "success"
            :local cm ""
            :do {{
              :do {{ /ppp/active/remove [find name=$uname] }} on-error={{}}
              :do {{ /ip/hotspot/active/remove [find user=$uname] }} on-error={{}}
              # Force the device back to the captive portal immediately: clear the
              # MAC-cookie + host binding so the next request re-authenticates
              # instead of staying logged in until the user toggles Wi-Fi.
              :do {{ /ip/hotspot/cookie/remove [find user=$uname] }} on-error={{}}
              :do {{ /ip/hotspot/host/remove [find user=$uname] }} on-error={{}}
            }} on-error={{ :set cs "failed"; :set cm "disconnect error" }}
{report}
          }}

          # --- DISABLE USER ---
          :if ($action = "disable_user") do={{
            :local sep2 [:find $rest "|"]
            :local sep3 [:find $rest "|" ($sep2 + 1)]
            :local uname [:pick $rest 0 $sep2]
            :local utype [:pick $rest ($sep2 + 1) $sep3]
            :local cid [:pick $rest ($sep3 + 1) [:len $rest]]
            :local cs "success"
            :local cm ""
            :do {{
              :if ($utype = "hotspot") do={{
                /ip/hotspot/user/set [find name=$uname] disabled=yes
                :do {{ /ip/hotspot/active/remove [find user=$uname] }} on-error={{}}
                # Force the captive portal on next request (no Wi-Fi toggle needed):
                # clear the MAC-cookie + host binding for the disabled user.
                :do {{ /ip/hotspot/cookie/remove [find user=$uname] }} on-error={{}}
                :do {{ /ip/hotspot/host/remove [find user=$uname] }} on-error={{}}
              }} else={{
                /ppp/secret/set [find name=$uname] disabled=yes
                :do {{ /ppp/active/remove [find name=$uname] }} on-error={{}}
              }}
            }} on-error={{ :set cs "failed"; :set cm "disable error" }}
{report}
          }}

          # --- ENABLE USER ---
          :if ($action = "enable_user") do={{
            :local sep2 [:find $rest "|"]
            :local sep3 [:find $rest "|" ($sep2 + 1)]
            :local uname [:pick $rest 0 $sep2]
            :local utype [:pick $rest ($sep2 + 1) $sep3]
            :local cid [:pick $rest ($sep3 + 1) [:len $rest]]
            :local cs "success"
            :local cm ""
            :do {{
              :if ($utype = "hotspot") do={{
                /ip/hotspot/user/set [find name=$uname] disabled=no
              }} else={{
                /ppp/secret/set [find name=$uname] disabled=no
              }}
            }} on-error={{ :set cs "failed"; :set cm "enable error" }}
{report}
          }}

          # --- CREATE USER ---
          :if ($action = "create_user") do={{
            :local sep2 [:find $rest "|"]
            :local sep3 [:find $rest "|" ($sep2 + 1)]
            :local sep4 [:find $rest "|" ($sep3 + 1)]
            :local sep5 [:find $rest "|" ($sep4 + 1)]
            :local sep6 [:find $rest "|" ($sep5 + 1)]
            :local uname [:pick $rest 0 $sep2]
            :local upass [:pick $rest ($sep2 + 1) $sep3]
            :local utype [:pick $rest ($sep3 + 1) $sep4]
            :local uprof [:pick $rest ($sep4 + 1) $sep5]
            :local urate [:pick $rest ($sep5 + 1) $sep6]
            :local cid [:pick $rest ($sep6 + 1) [:len $rest]]
            :local cs "success"
            :local cm ""
            :do {{
              :if ($utype = "hotspot") do={{
                # Ensure the plan profile exists with the correct bandwidth limit
                :if ([:len [/ip/hotspot/user/profile/find name=$uprof]] = 0) do={{
                  :if ([:len $urate] > 0) do={{ /ip/hotspot/user/profile/add name=$uprof rate-limit=$urate }} else={{ /ip/hotspot/user/profile/add name=$uprof }}
                }} else={{
                  :if ([:len $urate] > 0) do={{ /ip/hotspot/user/profile/set [find name=$uprof] rate-limit=$urate }}
                }}
                # IDEMPOTENT provision - preserve accumulated uptime (per-login-uptime
                # model). A returning customer re-logs in via this same create_user
                # queue on every Wi-Fi toggle; a blind remove+add would RESET the
                # cumulative uptime counter (revenue leak) or wrongly clear an
                # exhausted user. So: only ADD when absent; when present, update
                # password/profile IN PLACE (set never resets uptime) and only when
                # they actually changed - leaving an unchanged user fully intact.
                :if ([:len [/ip/hotspot/user/find name=$uname]] = 0) do={{
                  /ip/hotspot/user/add name=$uname password=$upass profile=$uprof
                }} else={{
                  :local cu [/ip/hotspot/user/get [find name=$uname]]
                  :if (($cu->"password") != $upass) do={{ /ip/hotspot/user/set [find name=$uname] password=$upass }}
                  :if (($cu->"profile") != $uprof) do={{ /ip/hotspot/user/set [find name=$uname] profile=$uprof }}
                }}
              }} else={{
                # Ensure the PPP profile exists with the correct bandwidth limit
                :if ([:len [/ppp/profile/find name=$uprof]] = 0) do={{
                  :if ([:len $urate] > 0) do={{ /ppp/profile/add name=$uprof rate-limit=$urate }} else={{ /ppp/profile/add name=$uprof }}
                }} else={{
                  :if ([:len $urate] > 0) do={{ /ppp/profile/set [find name=$uprof] rate-limit=$urate }}
                }}
                # IDEMPOTENT (see hotspot note): preserve uptime; add-if-absent,
                # else update credentials/profile in place only when changed.
                :if ([:len [/ppp/secret/find name=$uname]] = 0) do={{
                  /ppp/secret/add name=$uname password=$upass profile=$uprof service=pppoe
                }} else={{
                  :local cu [/ppp/secret/get [find name=$uname]]
                  :if (($cu->"password") != $upass) do={{ /ppp/secret/set [find name=$uname] password=$upass }}
                  :if (($cu->"profile") != $uprof) do={{ /ppp/secret/set [find name=$uname] profile=$uprof }}
                }}
              }}
            }} on-error={{ :set cs "failed"; :set cm "create error" }}
{report}
          }}

          # --- FETCH + IMPORT (full provisioning / arbitrary .rsc via agent) ---
          # Lets the cloud deliver Step-3 service setup to a NAT'd router: the
          # agent downloads a generated .rsc (provision-script) and imports it.
          :if ($action = "fetch_import") do={{
            :local sep2 [:find $rest "|"]
            :local furl [:pick $rest 0 $sep2]
            :local cid [:pick $rest ($sep2 + 1) [:len $rest]]
            :local cs "success"
            :local cm ""
            :do {{
              /tool/fetch url=$furl dst-path=cvcmd.rsc
              :delay 2s
              /import file-name=cvcmd.rsc
            }} on-error={{ :set cs "failed"; :set cm "fetch_import error" }}
{report}
          }}
        }}
      }}
    }}
  }}
}} on-error={{
  :log warning "CodeVertex agent: poll failed"
}}
"""
