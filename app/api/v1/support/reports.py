"""Reports and analytics API endpoints."""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, PaginationParams
from app.core.database import get_db
from app.models.organization import Organization
from app.models.user import User
from app.modules.analytics import ReportsService

router = APIRouter()


@router.get("/analytics/subscriptions")
async def get_subscription_analytics(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    plan_id: Optional[int] = Query(None),
    router_id: Optional[int] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get subscription analytics."""
    service = ReportsService(db)
    analytics = await service.get_subscription_analytics(
        start_date=start_date,
        end_date=end_date,
        plan_id=plan_id,
        router_id=router_id,
    )
    return analytics


@router.get("/analytics/billing")
async def get_billing_analytics(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get billing analytics."""
    service = ReportsService(db)
    analytics = await service.get_billing_analytics(
        start_date=start_date,
        end_date=end_date,
    )
    return analytics


@router.get("/analytics/routers")
async def get_router_analytics(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get router analytics."""
    service = ReportsService(db)
    analytics = await service.get_router_analytics(
        start_date=start_date,
        end_date=end_date,
    )
    return analytics


@router.get("/analytics/tickets")
async def get_ticket_analytics(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get support ticket analytics."""
    service = ReportsService(db)
    analytics = await service.get_ticket_analytics(
        start_date=start_date,
        end_date=end_date,
    )
    return analytics


@router.get("/analytics/dashboard")
async def get_dashboard_analytics(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get comprehensive dashboard analytics."""
    service = ReportsService(db)
    
    # Get all analytics
    subscription_analytics = await service.get_subscription_analytics(start_date, end_date)
    billing_analytics = await service.get_billing_analytics(start_date, end_date)
    router_analytics = await service.get_router_analytics(start_date, end_date)
    ticket_analytics = await service.get_ticket_analytics(start_date, end_date)
    
    # Fetch organization billing cycle info
    billing_cycle = None
    if current_user.organization_id:
        org_result = await db.execute(
            select(Organization).where(Organization.id == current_user.organization_id)
        )
        org = org_result.scalar_one_or_none()
        if org:
            billing_cycle = {
                "is_trial": org.is_trial,
                "trial_days_remaining": org.trial_days_remaining,
                "is_subscription_active": org.is_subscription_active,
                "subscription_days_remaining": org.subscription_days_remaining,
                "subscription_ends_at": org.subscription_ends_at.isoformat() if org.subscription_ends_at else None,
                "trial_ends_at": org.trial_ends_at.isoformat() if org.trial_ends_at else None,
                "status": org.status.value if org.status else None,
            }

    return {
        "subscriptions": subscription_analytics,
        "billing": billing_analytics,
        "routers": router_analytics,
        "tickets": ticket_analytics,
        "billing_cycle": billing_cycle,
        "generated_at": datetime.utcnow().isoformat(),
    }


@router.get("/analytics/dashboard-charts")
async def get_dashboard_charts(
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get all chart data for the dashboard in a single call."""
    service = ReportsService(db)
    return await service.get_dashboard_charts()


@router.get("/analytics/users")
async def get_user_analytics(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Get user analytics."""
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=30)
    if not end_date:
        end_date = datetime.utcnow()

    from sqlalchemy import select, func, and_
    from app.models.user import User as UserModel, UserRole

    total_q = select(func.count()).select_from(UserModel).where(
        and_(UserModel.created_at >= start_date, UserModel.created_at <= end_date)
    )
    active_q = select(func.count()).select_from(UserModel).where(
        and_(UserModel.created_at >= start_date, UserModel.created_at <= end_date, UserModel.is_active == True)
    )
    customer_q = select(func.count()).select_from(UserModel).where(
        and_(UserModel.created_at >= start_date, UserModel.created_at <= end_date, UserModel.role == UserRole.CUSTOMER)
    )

    total = (await db.execute(total_q)).scalar() or 0
    active = (await db.execute(active_q)).scalar() or 0
    customers = (await db.execute(customer_q)).scalar() or 0

    return {
        "total_users": total,
        "active_users": active,
        "total_customers": customers,
        "inactive_users": total - active,
    }


# CSV Report Endpoints
@router.get("/export/subscriptions/csv")
async def export_subscriptions_csv(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    plan_id: Optional[int] = Query(None),
    router_id: Optional[int] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export subscription report as CSV."""
    service = ReportsService(db)
    csv_data = await service.generate_subscription_report_csv(
        start_date=start_date,
        end_date=end_date,
        plan_id=plan_id,
        router_id=router_id,
    )
    
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=subscriptions_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        }
    )


@router.get("/export/billing/csv")
async def export_billing_csv(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export billing report as CSV."""
    service = ReportsService(db)
    csv_data = await service.generate_billing_report_csv(
        start_date=start_date,
        end_date=end_date,
    )
    
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=billing_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        }
    )


# PDF Report Endpoints
@router.get("/export/subscriptions/pdf")
async def export_subscriptions_pdf(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    plan_id: Optional[int] = Query(None),
    router_id: Optional[int] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export subscription report as PDF."""
    service = ReportsService(db)
    pdf_data = await service.generate_pdf_report(
        report_type="subscriptions",
        start_date=start_date,
        end_date=end_date,
        plan_id=plan_id,
        router_id=router_id,
    )
    
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=subscriptions_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        }
    )


@router.get("/export/billing/pdf")
async def export_billing_pdf(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export billing report as PDF."""
    service = ReportsService(db)
    pdf_data = await service.generate_pdf_report(
        report_type="billing",
        start_date=start_date,
        end_date=end_date,
    )
    
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=billing_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        }
    )


@router.get("/export/routers/pdf")
async def export_routers_pdf(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export router report as PDF."""
    service = ReportsService(db)
    pdf_data = await service.generate_pdf_report(
        report_type="routers",
        start_date=start_date,
        end_date=end_date,
    )
    
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=routers_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        }
    )


@router.get("/export/tickets/pdf")
async def export_tickets_pdf(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export support ticket report as PDF."""
    service = ReportsService(db)
    pdf_data = await service.generate_pdf_report(
        report_type="tickets",
        start_date=start_date,
        end_date=end_date,
    )
    
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=tickets_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        }
    )


# Excel Report Endpoints
@router.get("/export/subscriptions/excel")
async def export_subscriptions_excel(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    plan_id: Optional[int] = Query(None),
    router_id: Optional[int] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export subscription report as Excel."""
    service = ReportsService(db)
    excel_data = await service.generate_excel_report(
        report_type="subscriptions",
        start_date=start_date,
        end_date=end_date,
        plan_id=plan_id,
        router_id=router_id,
    )
    
    return Response(
        content=excel_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=subscriptions_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
        }
    )


@router.get("/export/billing/excel")
async def export_billing_excel(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export billing report as Excel."""
    service = ReportsService(db)
    excel_data = await service.generate_excel_report(
        report_type="billing",
        start_date=start_date,
        end_date=end_date,
    )
    
    return Response(
        content=excel_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=billing_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
        }
    )


@router.get("/export/routers/excel")
async def export_routers_excel(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export router report as Excel."""
    service = ReportsService(db)
    excel_data = await service.generate_excel_report(
        report_type="routers",
        start_date=start_date,
        end_date=end_date,
    )
    
    return Response(
        content=excel_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=routers_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
        }
    )


@router.get("/export/tickets/excel")
async def export_tickets_excel(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export support ticket report as Excel."""
    service = ReportsService(db)
    excel_data = await service.generate_excel_report(
        report_type="tickets",
        start_date=start_date,
        end_date=end_date,
    )
    
    return Response(
        content=excel_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=tickets_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
        }
    )


# Comprehensive Report Endpoints
@router.get("/export/comprehensive/excel")
async def export_comprehensive_excel(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export comprehensive report as Excel with all data."""
    service = ReportsService(db)
    
    # Generate a comprehensive Excel file with multiple sheets
    import io
    import pandas as pd
    
    buffer = io.BytesIO()
    
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        # Subscriptions sheet
        subscription_analytics = await service.get_subscription_analytics(start_date, end_date)
        subscription_data = [
            ["Metric", "Value"],
            ["Total Subscriptions", subscription_analytics["total_subscriptions"]],
            ["Active Subscriptions", subscription_analytics["active_subscriptions"]],
            ["Expired Subscriptions", subscription_analytics["expired_subscriptions"]],
            ["Total Data Used (GB)", subscription_analytics["total_data_used"]],
            ["Average Sessions", subscription_analytics["average_sessions"]],
        ]
        subscription_df = pd.DataFrame(subscription_data[1:], columns=subscription_data[0])
        subscription_df.to_excel(writer, sheet_name='Subscriptions', index=False)
        
        # Billing sheet
        billing_analytics = await service.get_billing_analytics(start_date, end_date)
        billing_data = [
            ["Metric", "Value"],
            ["Total Invoices", billing_analytics["total_invoices"]],
            ["Total Revenue", billing_analytics["total_revenue"]],
            ["Paid Invoices", billing_analytics["paid_invoices"]],
            ["Pending Invoices", billing_analytics["pending_invoices"]],
            ["Overdue Invoices", billing_analytics["overdue_invoices"]],
            ["Collection Rate", billing_analytics["collection_rate"]],
            ["Average Invoice Amount", billing_analytics["average_invoice_amount"]],
        ]
        billing_df = pd.DataFrame(billing_data[1:], columns=billing_data[0])
        billing_df.to_excel(writer, sheet_name='Billing', index=False)
        
        # Routers sheet
        router_analytics = await service.get_router_analytics(start_date, end_date)
        router_data = [
            ["Metric", "Value"],
            ["Total Routers", router_analytics["total_routers"]],
            ["Online Routers", router_analytics["online_routers"]],
            ["Offline Routers", router_analytics["offline_routers"]],
            ["Total Subscriptions", router_analytics["total_subscriptions"]],
            ["Average Uptime", router_analytics["average_uptime"]],
        ]
        router_df = pd.DataFrame(router_data[1:], columns=router_data[0])
        router_df.to_excel(writer, sheet_name='Routers', index=False)
        
        # Tickets sheet
        ticket_analytics = await service.get_ticket_analytics(start_date, end_date)
        ticket_data = [
            ["Metric", "Value"],
            ["Total Tickets", ticket_analytics["total_tickets"]],
            ["Open Tickets", ticket_analytics["open_tickets"]],
            ["Resolved Tickets", ticket_analytics["resolved_tickets"]],
            ["Closed Tickets", ticket_analytics["closed_tickets"]],
            ["Average Resolution Time", ticket_analytics["average_resolution_time"]],
        ]
        ticket_df = pd.DataFrame(ticket_data[1:], columns=ticket_data[0])
        ticket_df.to_excel(writer, sheet_name='Tickets', index=False)
    
    buffer.seek(0)
    excel_data = buffer.getvalue()
    
    return Response(
        content=excel_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=comprehensive_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
        }
    )


@router.get("/export/comprehensive/pdf")
async def export_comprehensive_pdf(
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export comprehensive report as PDF with all data."""
    service = ReportsService(db)
    
    # Generate a comprehensive PDF with all analytics
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        alignment=TA_CENTER
    )
    story.append(Paragraph("Comprehensive ISP Billing Report", title_style))
    story.append(Spacer(1, 12))
    
    # Date range
    if start_date and end_date:
        date_text = f"Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        story.append(Paragraph(date_text, styles['Normal']))
        story.append(Spacer(1, 12))
    
    # Get all analytics
    subscription_analytics = await service.get_subscription_analytics(start_date, end_date)
    billing_analytics = await service.get_billing_analytics(start_date, end_date)
    router_analytics = await service.get_router_analytics(start_date, end_date)
    ticket_analytics = await service.get_ticket_analytics(start_date, end_date)
    
    # Subscriptions section
    story.append(Paragraph("Subscriptions", styles['Heading2']))
    subscription_data = [
        ["Metric", "Value"],
        ["Total Subscriptions", str(subscription_analytics["total_subscriptions"])],
        ["Active Subscriptions", str(subscription_analytics["active_subscriptions"])],
        ["Expired Subscriptions", str(subscription_analytics["expired_subscriptions"])],
        ["Total Data Used (GB)", f"{subscription_analytics['total_data_used']:.2f}"],
        ["Average Sessions", f"{subscription_analytics['average_sessions']:.2f}"],
    ]
    
    table = Table(subscription_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(table)
    story.append(Spacer(1, 20))
    
    # Billing section
    story.append(Paragraph("Billing", styles['Heading2']))
    billing_data = [
        ["Metric", "Value"],
        ["Total Invoices", str(billing_analytics["total_invoices"])],
        ["Total Revenue", f"${billing_analytics['total_revenue']:.2f}"],
        ["Paid Invoices", str(billing_analytics["paid_invoices"])],
        ["Pending Invoices", str(billing_analytics["pending_invoices"])],
        ["Overdue Invoices", str(billing_analytics["overdue_invoices"])],
        ["Collection Rate", f"{billing_analytics['collection_rate']:.1f}%"],
        ["Average Invoice Amount", f"${billing_analytics['average_invoice_amount']:.2f}"],
    ]
    
    table = Table(billing_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(table)
    story.append(Spacer(1, 20))
    
    # Routers section
    story.append(Paragraph("Routers", styles['Heading2']))
    router_data = [
        ["Metric", "Value"],
        ["Total Routers", str(router_analytics["total_routers"])],
        ["Online Routers", str(router_analytics["online_routers"])],
        ["Offline Routers", str(router_analytics["offline_routers"])],
        ["Total Subscriptions", str(router_analytics["total_subscriptions"])],
        ["Average Uptime", f"{router_analytics['average_uptime']:.1f} hours"],
    ]
    
    table = Table(router_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(table)
    story.append(Spacer(1, 20))
    
    # Tickets section
    story.append(Paragraph("Support Tickets", styles['Heading2']))
    ticket_data = [
        ["Metric", "Value"],
        ["Total Tickets", str(ticket_analytics["total_tickets"])],
        ["Open Tickets", str(ticket_analytics["open_tickets"])],
        ["Resolved Tickets", str(ticket_analytics["resolved_tickets"])],
        ["Closed Tickets", str(ticket_analytics["closed_tickets"])],
        ["Average Resolution Time", f"{ticket_analytics['average_resolution_time']:.1f} hours"],
    ]
    
    table = Table(ticket_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    story.append(table)
    
    doc.build(story)
    buffer.seek(0)
    pdf_data = buffer.getvalue()
    
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=comprehensive_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        }
    )
