"""Template serving endpoints for MikroTik hotspot customization.

This module provides endpoints to serve customized HTML templates for hotspot login pages.
The templates are dynamically generated with organization-specific branding and portal URLs.
"""
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.organization import Organization, OrganizationSettings
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def get_captive_portal_url(org_slug: str) -> str:
    """Generate the captive portal URL for an organization.

    Args:
        org_slug: Organization slug identifier

    Returns:
        Full captive portal URL for the organization
    """
    # Frontend captive portal URL (where users buy packages)
    frontend_url = settings.frontend_url or "http://localhost:3000"
    return f"{frontend_url}/buy/{org_slug}"


def generate_login_template(captive_portal_url: str, org_name: str = "ISP") -> str:
    """Generate login.html template that redirects to buy packages page.

    This page redirects users directly to the buy packages page when they try to access the internet.
    The login form is only shown as a fallback if they already have credentials.

    Args:
        captive_portal_url: URL where users can purchase packages
        org_name: Organization name for branding

    Returns:
        HTML content for redirect page with fallback login
    """
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="0; url={captive_portal_url}?mac=$(mac)&ip=$(ip)&username=$(username)&link-orig=$(link-orig-esc)">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{org_name} - WiFi Portal</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            max-width: 400px;
            width: 100%;
            padding: 40px;
            text-align: center;
        }}
        .spinner {{
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            animation: spin 1s linear infinite;
            margin: 0 auto 1.5rem;
        }}
        @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
        }}
        h1 {{
            color: #667eea;
            font-size: 28px;
            margin-bottom: 10px;
        }}
        p {{
            color: #666;
            margin-bottom: 20px;
        }}
        a {{
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .login-fallback {{
            margin-top: 30px;
            padding-top: 30px;
            border-top: 1px solid #e0e0e0;
        }}
        .form-group {{
            margin-bottom: 15px;
            text-align: left;
        }}
        label {{
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 500;
            font-size: 14px;
        }}
        input[type="text"],
        input[type="password"] {{
            width: 100%;
            padding: 12px 16px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.3s;
        }}
        input:focus {{
            outline: none;
            border-color: #667eea;
        }}
        button {{
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(102, 126, 234, 0.4);
        }}
        .error {{
            color: #dc3545;
            text-align: center;
            margin-bottom: 20px;
            padding: 10px;
            background: #fee;
            border-radius: 8px;
            display: none;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="spinner"></div>
        <h1>{org_name}</h1>
        <p>Redirecting to portal...</p>
        <p>If not redirected automatically, <a href="{captive_portal_url}?mac=$(mac)&ip=$(ip)&username=$(username)&link-orig=$(link-orig-esc)">click here</a></p>

        <div class="login-fallback">
            <p style="font-size: 14px; color: #999; margin-bottom: 15px;">Already have credentials? Login below:</p>

            <div class="error" id="error"></div>

            <form name="login" action="$(link-login-only)" method="post">
                <input type="hidden" name="dst" value="$(link-orig)" />

                <div class="form-group">
                    <label for="username">Username</label>
                    <input type="text"
                           id="username"
                           name="username"
                           placeholder="Enter your username"
                           value="$(username)" />
                </div>

                <div class="form-group">
                    <label for="password">Password</label>
                    <input type="password"
                           id="password"
                           name="password"
                           placeholder="Enter your password" />
                </div>

                <button type="submit">Connect</button>
            </form>
        </div>
    </div>

    <script>
        // Immediately redirect to the external buy/redeem portal, carrying the
        // MikroTik login endpoint ($(link-login-only)) + original URL so the
        // portal can log THIS client into the hotspot after purchase/redeem.
        // encodeURIComponent is required: link-login-only contains "://" and "/".
        (function() {{
            try {{
                var portal = '{captive_portal_url}';
                var sep = portal.indexOf('?') >= 0 ? '&' : '?';
                window.location.href = portal + sep +
                    'loginurl=' + encodeURIComponent('$(link-login-only)') +
                    '&linkorig=' + encodeURIComponent('$(link-orig)') +
                    '&mac=' + encodeURIComponent('$(mac)') +
                    '&ip=' + encodeURIComponent('$(ip)');
            }} catch (e) {{}}
        }})();

        // Show error if login failed
        var error = '$(error)';
        if (error && error.length > 0) {{
            document.getElementById('error').textContent = error;
            document.getElementById('error').style.display = 'block';
        }}
    </script>
</body>
</html>'''


def generate_alogin_template(captive_portal_url: str, redirect_url: str, org_name: str = "ISP") -> str:
    """Generate alogin.html template (post-authentication page).

    This page is shown after successful login and redirects to the org's redirect URL.

    Args:
        captive_portal_url: URL where users can purchase packages
        redirect_url: URL to redirect after successful authentication
        org_name: Organization name for branding

    Returns:
        HTML content for post-login page
    """
    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="2; url={redirect_url}">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{org_name} - Connected</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .container {{
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            max-width: 500px;
            width: 100%;
            padding: 40px;
            text-align: center;
        }}
        .success-icon {{
            width: 80px;
            height: 80px;
            margin: 0 auto 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 40px;
        }}
        h1 {{
            color: #667eea;
            font-size: 28px;
            margin-bottom: 10px;
        }}
        .welcome {{
            color: #333;
            font-size: 18px;
            margin-bottom: 20px;
        }}
        .info {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
        }}
        .info-item {{
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #e0e0e0;
        }}
        .info-item:last-child {{
            border-bottom: none;
        }}
        .info-label {{
            color: #666;
            font-weight: 500;
        }}
        .info-value {{
            color: #333;
            font-weight: 600;
        }}
        button {{
            margin-top: 20px;
            padding: 12px 30px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(102, 126, 234, 0.4);
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #e0e0e0;
            color: #666;
        }}
        .footer a {{
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="success-icon">✓</div>
        <h1>Connected Successfully!</h1>
        <p class="welcome">Welcome, <strong>$(username)</strong></p>

        <div class="info">
            <div class="info-item">
                <span class="info-label">Session Time</span>
                <span class="info-value" id="uptime">$(uptime)</span>
            </div>
            <div class="info-item">
                <span class="info-label">Downloaded</span>
                <span class="info-value" id="bytes-in">$(bytes-in-nice)</span>
            </div>
            <div class="info-item">
                <span class="info-label">Uploaded</span>
                <span class="info-value" id="bytes-out">$(bytes-out-nice)</span>
            </div>
            <div class="info-item">
                <span class="info-label">IP Address</span>
                <span class="info-value">$(ip)</span>
            </div>
        </div>

        <p style="color: #667eea; font-size: 14px; margin: 20px 0;">Redirecting you in 2 seconds...</p>

        <form name="logout" action="$(link-logout)" method="post">
            <button type="submit">Disconnect</button>
        </form>

        <div class="footer">
            <p>Need more data or time?</p>
            <a href="{captive_portal_url}" target="_blank">Buy Package</a>
        </div>
    </div>

    <script>
        // Auto-redirect after 2 seconds
        setTimeout(function() {{
            window.location.href = '{redirect_url}';
        }}, 2000);
    </script>
</body>
</html>'''


@router.get("/templates/login.html", response_class=HTMLResponse)
async def get_login_template(
    org_slug: str = Query(..., description="Organization slug identifier"),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Serve customized login.html template for MikroTik hotspot.

    This endpoint is called by the MikroTik router during bootstrap to download
    the login page template with organization-specific branding.

    Args:
        org_slug: Organization slug for customization
        db: Database session

    Returns:
        HTML content for hotspot login page that redirects to buy packages

    Raises:
        HTTPException: If organization not found
    """
    # Fetch organization details for branding
    async for session in get_db():
        result = await session.execute(
            select(Organization).where(Organization.slug == org_slug)
        )
        organization = result.scalar_one_or_none()

        if not organization:
            logger.warning(f"Organization not found for slug: {org_slug}")
            raise HTTPException(status_code=404, detail=f"Organization '{org_slug}' not found")

        # Generate captive portal URL (buy packages page)
        captive_portal_url = get_captive_portal_url(org_slug)

        # Generate and return template
        template_content = generate_login_template(
            captive_portal_url=captive_portal_url,
            org_name=organization.name
        )

        logger.info(f"Served login.html template for organization: {org_slug} (redirects to buy packages)")
        return template_content


@router.get("/templates/alogin.html", response_class=HTMLResponse)
async def get_alogin_template(
    org_slug: str = Query(..., description="Organization slug identifier"),
    db: AsyncSession = Depends(get_db),
) -> str:
    """Serve customized alogin.html template for MikroTik hotspot.

    This endpoint is called by the MikroTik router during bootstrap to download
    the post-authentication page template with organization-specific branding.

    Args:
        org_slug: Organization slug for customization
        db: Database session

    Returns:
        HTML content for post-authentication page that redirects to org's redirect URL

    Raises:
        HTTPException: If organization not found
    """
    # Fetch organization details for branding
    async for session in get_db():
        result = await session.execute(
            select(Organization).where(Organization.slug == org_slug)
        )
        organization = result.scalar_one_or_none()

        if not organization:
            logger.warning(f"Organization not found for slug: {org_slug}")
            raise HTTPException(status_code=404, detail=f"Organization '{org_slug}' not found")

        # Fetch organization settings for redirect URL
        settings_result = await session.execute(
            select(OrganizationSettings).where(OrganizationSettings.organization_id == organization.id)
        )
        org_settings = settings_result.scalar_one_or_none()

        # Generate captive portal URL (buy packages page)
        captive_portal_url = get_captive_portal_url(org_slug)

        # Get redirect URL from settings or use default
        redirect_url = org_settings.hotspot_redirect_url if org_settings else "https://www.google.com"

        # Generate and return template
        template_content = generate_alogin_template(
            captive_portal_url=captive_portal_url,
            redirect_url=redirect_url,
            org_name=organization.name
        )

        logger.info(f"Served alogin.html template for organization: {org_slug} (redirects to {redirect_url})")
        return template_content
