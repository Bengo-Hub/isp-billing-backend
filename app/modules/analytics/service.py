"""Reports and analytics service using Polars for data processing."""

import io
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union
from decimal import Decimal

import polars as pl
import pandas as pd
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from jinja2 import Template
from sqlalchemy import select, func, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionUsageLog
from app.models.billing import Invoice, Payment, InvoiceStatus, PaymentStatus
from app.models.plan import ServicePlan, PlanType
from app.models.router import Router, RouterStatus
from app.models.notification import SupportTicket, TicketStatus, TicketPriority
from app.api.deps import PaginationParams


class ReportsService:
    """Reports and analytics service using Polars for data processing."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_subscription_analytics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        plan_id: Optional[int] = None,
        router_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get subscription analytics data."""
        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=30)
        if not end_date:
            end_date = datetime.utcnow()

        # Build query
        query = select(Subscription).where(
            and_(
                Subscription.created_at >= start_date,
                Subscription.created_at <= end_date
            )
        )

        if plan_id:
            query = query.where(Subscription.plan_id == plan_id)
        if router_id:
            query = query.where(Subscription.router_id == router_id)

        result = await self.db.execute(query)
        subscriptions = result.scalars().all()

        # Convert to Polars DataFrame
        data = []
        for sub in subscriptions:
            data.append({
                "id": sub.id,
                "user_id": sub.user_id,
                "plan_id": sub.plan_id,
                "router_id": sub.router_id,
                "status": sub.status.value,
                "subscription_type": sub.subscription_type.value,
                "username": sub.username,
                "start_date": sub.start_date,
                "end_date": sub.end_date,
                "created_at": sub.created_at,
                "total_bytes_used": sub.total_bytes_used,
                "total_data_used_gb": float(sub.total_data_used_gb),
                "session_count": sub.session_count,
                "last_activity": sub.last_activity,
                "is_active": sub.is_active,
                "is_expired": sub.is_expired,
            })

        if not data:
            return {
                "total_subscriptions": 0,
                "active_subscriptions": 0,
                "expired_subscriptions": 0,
                "total_data_used": 0,
                "average_sessions": 0,
                "subscriptions_by_status": {},
                "subscriptions_by_type": {},
                "monthly_trends": [],
            }

        df = pl.DataFrame(data)

        # Calculate analytics
        total_subscriptions = len(df)
        active_subscriptions = len(df.filter(pl.col("is_active") == True))
        expired_subscriptions = len(df.filter(pl.col("is_expired") == True))
        total_data_used = df["total_data_used_gb"].sum()
        average_sessions = df["session_count"].mean()

        # Group by status
        subscriptions_by_status = (
            df.group_by("status")
            .agg(pl.count().alias("count"))
            .to_dicts()
        )

        # Group by type
        subscriptions_by_type = (
            df.group_by("subscription_type")
            .agg(pl.count().alias("count"))
            .to_dicts()
        )

        # Monthly trends
        monthly_trends = (
            df.with_columns(
                pl.col("created_at").dt.strftime("%Y-%m").alias("month")
            )
            .group_by("month")
            .agg(pl.count().alias("count"))
            .sort("month")
            .to_dicts()
        )

        return {
            "total_subscriptions": total_subscriptions,
            "active_subscriptions": active_subscriptions,
            "expired_subscriptions": expired_subscriptions,
            "total_data_used": total_data_used,
            "average_sessions": average_sessions,
            "subscriptions_by_status": {item["status"]: item["count"] for item in subscriptions_by_status},
            "subscriptions_by_type": {item["subscription_type"]: item["count"] for item in subscriptions_by_type},
            "monthly_trends": monthly_trends,
        }

    async def get_billing_analytics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get billing analytics data."""
        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=30)
        if not end_date:
            end_date = datetime.utcnow()

        # Get invoices
        invoice_query = select(Invoice).where(
            and_(
                Invoice.created_at >= start_date,
                Invoice.created_at <= end_date
            )
        )
        invoice_result = await self.db.execute(invoice_query)
        invoices = invoice_result.scalars().all()

        # Get payments
        payment_query = select(Payment).where(
            and_(
                Payment.created_at >= start_date,
                Payment.created_at <= end_date
            )
        )
        payment_result = await self.db.execute(payment_query)
        payments = payment_result.scalars().all()

        # Convert to Polars DataFrames
        invoice_data = []
        for inv in invoices:
            invoice_data.append({
                "id": inv.id,
                "user_id": inv.user_id,
                "subscription_id": inv.subscription_id,
                "invoice_number": inv.invoice_number,
                "subtotal": float(inv.subtotal),
                "tax_amount": float(inv.tax_amount),
                "discount_amount": float(inv.discount_amount),
                "total_amount": float(inv.total_amount),
                "paid_amount": float(inv.paid_amount),
                "balance": float(inv.balance),
                "status": inv.status.value,
                "issue_date": inv.issue_date,
                "due_date": inv.due_date,
                "paid_date": inv.paid_date,
                "created_at": inv.created_at,
            })

        payment_data = []
        for pay in payments:
            payment_data.append({
                "id": pay.id,
                "user_id": pay.user_id,
                "invoice_id": pay.invoice_id,
                "amount": float(pay.amount),
                "payment_method": pay.payment_method.value,
                "status": pay.status.value,
                "payment_date": pay.payment_date,
                "created_at": pay.created_at,
            })

        if not invoice_data and not payment_data:
            return {
                "total_invoices": 0,
                "total_revenue": 0,
                "paid_invoices": 0,
                "pending_invoices": 0,
                "overdue_invoices": 0,
                "collection_rate": 0,
                "average_invoice_amount": 0,
                "revenue_by_month": [],
                "payment_methods": {},
            }

        invoice_df = pl.DataFrame(invoice_data) if invoice_data else pl.DataFrame()
        payment_df = pl.DataFrame(payment_data) if payment_data else pl.DataFrame()

        # Calculate analytics
        total_invoices = len(invoice_df) if not invoice_df.is_empty() else 0
        total_revenue = invoice_df["paid_amount"].sum() if not invoice_df.is_empty() else 0
        paid_invoices = len(invoice_df.filter(pl.col("status") == "paid")) if not invoice_df.is_empty() else 0
        pending_invoices = len(invoice_df.filter(pl.col("status") == "pending")) if not invoice_df.is_empty() else 0
        overdue_invoices = len(invoice_df.filter(pl.col("status") == "overdue")) if not invoice_df.is_empty() else 0
        collection_rate = (paid_invoices / total_invoices * 100) if total_invoices > 0 else 0
        average_invoice_amount = invoice_df["total_amount"].mean() if not invoice_df.is_empty() else 0

        # Revenue by month
        revenue_by_month = []
        if not invoice_df.is_empty():
            revenue_by_month = (
                invoice_df.with_columns(
                    pl.col("issue_date").dt.strftime("%Y-%m").alias("month")
                )
                .group_by("month")
                .agg(pl.col("paid_amount").sum().alias("revenue"))
                .sort("month")
                .to_dicts()
            )

        # Payment methods
        payment_methods = {}
        if not payment_df.is_empty():
            payment_methods = (
                payment_df.group_by("payment_method")
                .agg(pl.count().alias("count"))
                .to_dicts()
            )
            payment_methods = {item["payment_method"]: item["count"] for item in payment_methods}

        return {
            "total_invoices": total_invoices,
            "total_revenue": total_revenue,
            "paid_invoices": paid_invoices,
            "pending_invoices": pending_invoices,
            "overdue_invoices": overdue_invoices,
            "collection_rate": collection_rate,
            "average_invoice_amount": average_invoice_amount,
            "revenue_by_month": revenue_by_month,
            "payment_methods": payment_methods,
        }

    async def get_router_analytics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get router analytics data."""
        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=30)
        if not end_date:
            end_date = datetime.utcnow()

        # Get routers
        router_query = select(Router)
        router_result = await self.db.execute(router_query)
        routers = router_result.scalars().all()

        # Get subscriptions for router usage
        subscription_query = select(Subscription).where(
            and_(
                Subscription.created_at >= start_date,
                Subscription.created_at <= end_date
            )
        )
        subscription_result = await self.db.execute(subscription_query)
        subscriptions = subscription_result.scalars().all()

        # Convert to Polars DataFrames
        router_data = []
        for router in routers:
            router_data.append({
                "id": router.id,
                "name": router.name,
                "ip_address": router.ip_address,
                "status": router.status.value,
                "router_type": router.router_type.value,
                "location": router.location,
                "uptime": router.uptime,
                "last_seen": router.last_seen,
                "created_at": router.created_at,
            })

        subscription_data = []
        for sub in subscriptions:
            subscription_data.append({
                "id": sub.id,
                "router_id": sub.router_id,
                "status": sub.status.value,
                "total_bytes_used": sub.total_bytes_used,
                "total_data_used_gb": float(sub.total_data_used_gb),
                "session_count": sub.session_count,
                "last_activity": sub.last_activity,
            })

        if not router_data:
            return {
                "total_routers": 0,
                "online_routers": 0,
                "offline_routers": 0,
                "total_subscriptions": 0,
                "average_uptime": 0,
                "routers_by_status": {},
                "routers_by_type": {},
            }

        router_df = pl.DataFrame(router_data)
        subscription_df = pl.DataFrame(subscription_data) if subscription_data else pl.DataFrame()

        # Calculate analytics
        total_routers = len(router_df)
        online_routers = len(router_df.filter(pl.col("status") == "online"))
        offline_routers = len(router_df.filter(pl.col("status") == "offline"))
        total_subscriptions = len(subscription_df) if not subscription_df.is_empty() else 0
        average_uptime = router_df["uptime"].mean()

        # Group by status
        routers_by_status = (
            router_df.group_by("status")
            .agg(pl.count().alias("count"))
            .to_dicts()
        )

        # Group by type
        routers_by_type = (
            router_df.group_by("router_type")
            .agg(pl.count().alias("count"))
            .to_dicts()
        )

        return {
            "total_routers": total_routers,
            "online_routers": online_routers,
            "offline_routers": offline_routers,
            "total_subscriptions": total_subscriptions,
            "average_uptime": average_uptime,
            "routers_by_status": {item["status"]: item["count"] for item in routers_by_status},
            "routers_by_type": {item["router_type"]: item["count"] for item in routers_by_type},
        }

    async def get_ticket_analytics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get support ticket analytics data."""
        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=30)
        if not end_date:
            end_date = datetime.utcnow()

        # Get tickets
        ticket_query = select(SupportTicket).where(
            and_(
                SupportTicket.created_at >= start_date,
                SupportTicket.created_at <= end_date
            )
        )
        ticket_result = await self.db.execute(ticket_query)
        tickets = ticket_result.scalars().all()

        # Convert to Polars DataFrame
        data = []
        for ticket in tickets:
            data.append({
                "id": ticket.id,
                "user_id": ticket.user_id,
                "ticket_number": ticket.ticket_number,
                "subject": ticket.subject,
                "status": ticket.status.value,
                "priority": ticket.priority.value,
                "category": ticket.category,
                "assigned_to": ticket.assigned_to,
                "created_at": ticket.created_at,
                "resolved_at": ticket.resolved_at,
                "closed_at": ticket.closed_at,
            })

        if not data:
            return {
                "total_tickets": 0,
                "open_tickets": 0,
                "resolved_tickets": 0,
                "closed_tickets": 0,
                "average_resolution_time": 0,
                "tickets_by_status": {},
                "tickets_by_priority": {},
                "tickets_by_category": {},
            }

        df = pl.DataFrame(data)

        # Calculate analytics
        total_tickets = len(df)
        open_tickets = len(df.filter(pl.col("status") == "open"))
        resolved_tickets = len(df.filter(pl.col("status") == "resolved"))
        closed_tickets = len(df.filter(pl.col("status") == "closed"))

        # Calculate average resolution time
        resolved_df = df.filter(pl.col("resolved_at").is_not_null())
        if not resolved_df.is_empty():
            resolution_times = (
                resolved_df.with_columns(
                    (pl.col("resolved_at") - pl.col("created_at")).dt.total_hours().alias("resolution_hours")
                )
                .select("resolution_hours")
                .to_series()
            )
            average_resolution_time = resolution_times.mean()
        else:
            average_resolution_time = 0

        # Group by status
        tickets_by_status = (
            df.group_by("status")
            .agg(pl.count().alias("count"))
            .to_dicts()
        )

        # Group by priority
        tickets_by_priority = (
            df.group_by("priority")
            .agg(pl.count().alias("count"))
            .to_dicts()
        )

        # Group by category
        tickets_by_category = (
            df.filter(pl.col("category").is_not_null())
            .group_by("category")
            .agg(pl.count().alias("count"))
            .to_dicts()
        )

        return {
            "total_tickets": total_tickets,
            "open_tickets": open_tickets,
            "resolved_tickets": resolved_tickets,
            "closed_tickets": closed_tickets,
            "average_resolution_time": average_resolution_time,
            "tickets_by_status": {item["status"]: item["count"] for item in tickets_by_status},
            "tickets_by_priority": {item["priority"]: item["count"] for item in tickets_by_priority},
            "tickets_by_category": {item["category"]: item["count"] for item in tickets_by_category},
        }

    async def generate_subscription_report_csv(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        plan_id: Optional[int] = None,
        router_id: Optional[int] = None,
    ) -> bytes:
        """Generate subscription report as CSV."""
        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=30)
        if not end_date:
            end_date = datetime.utcnow()

        # Get detailed subscription data
        query = select(Subscription).where(
            and_(
                Subscription.created_at >= start_date,
                Subscription.created_at <= end_date
            )
        )

        if plan_id:
            query = query.where(Subscription.plan_id == plan_id)
        if router_id:
            query = query.where(Subscription.router_id == router_id)

        result = await self.db.execute(query)
        subscriptions = result.scalars().all()

        # Convert to Polars DataFrame
        data = []
        for sub in subscriptions:
            data.append({
                "ID": sub.id,
                "Username": sub.username,
                "Status": sub.status.value,
                "Type": sub.subscription_type.value,
                "Start Date": sub.start_date.strftime("%Y-%m-%d"),
                "End Date": sub.end_date.strftime("%Y-%m-%d"),
                "Data Used (GB)": float(sub.total_data_used_gb),
                "Sessions": sub.session_count,
                "Last Activity": sub.last_activity.strftime("%Y-%m-%d %H:%M:%S") if sub.last_activity else "Never",
                "Created": sub.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            })

        if not data:
            return b"ID,Username,Status,Type,Start Date,End Date,Data Used (GB),Sessions,Last Activity,Created\n"

        df = pl.DataFrame(data)
        return df.write_csv().encode()

    async def generate_billing_report_csv(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> bytes:
        """Generate billing report as CSV."""
        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=30)
        if not end_date:
            end_date = datetime.utcnow()

        # Get detailed billing data
        invoice_query = select(Invoice).where(
            and_(
                Invoice.created_at >= start_date,
                Invoice.created_at <= end_date
            )
        )
        invoice_result = await self.db.execute(invoice_query)
        invoices = invoice_result.scalars().all()

        # Convert to Polars DataFrame
        data = []
        for inv in invoices:
            data.append({
                "Invoice Number": inv.invoice_number,
                "User ID": inv.user_id,
                "Subscription ID": inv.subscription_id,
                "Subtotal": float(inv.subtotal),
                "Tax": float(inv.tax_amount),
                "Discount": float(inv.discount_amount),
                "Total": float(inv.total_amount),
                "Paid": float(inv.paid_amount),
                "Balance": float(inv.balance),
                "Status": inv.status.value,
                "Issue Date": inv.issue_date.strftime("%Y-%m-%d"),
                "Due Date": inv.due_date.strftime("%Y-%m-%d"),
                "Paid Date": inv.paid_date.strftime("%Y-%m-%d") if inv.paid_date else "",
                "Created": inv.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            })

        if not data:
            return b"Invoice Number,User ID,Subscription ID,Subtotal,Tax,Discount,Total,Paid,Balance,Status,Issue Date,Due Date,Paid Date,Created\n"

        df = pl.DataFrame(data)
        return df.write_csv().encode()

    async def generate_pdf_report(
        self,
        report_type: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        **kwargs
    ) -> bytes:
        """Generate PDF report."""
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
        story.append(Paragraph(f"{report_type.title()} Report", title_style))
        story.append(Spacer(1, 12))

        # Date range
        if start_date and end_date:
            date_text = f"Period: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
            story.append(Paragraph(date_text, styles['Normal']))
            story.append(Spacer(1, 12))

        # Generate report content based on type
        if report_type == "subscriptions":
            await self._add_subscription_pdf_content(story, styles, start_date, end_date, **kwargs)
        elif report_type == "billing":
            await self._add_billing_pdf_content(story, styles, start_date, end_date, **kwargs)
        elif report_type == "routers":
            await self._add_router_pdf_content(story, styles, start_date, end_date, **kwargs)
        elif report_type == "tickets":
            await self._add_ticket_pdf_content(story, styles, start_date, end_date, **kwargs)

        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()

    async def _add_subscription_pdf_content(self, story, styles, start_date, end_date, **kwargs):
        """Add subscription content to PDF."""
        analytics = await self.get_subscription_analytics(start_date, end_date, **kwargs)
        
        # Summary table
        summary_data = [
            ["Metric", "Value"],
            ["Total Subscriptions", str(analytics["total_subscriptions"])],
            ["Active Subscriptions", str(analytics["active_subscriptions"])],
            ["Expired Subscriptions", str(analytics["expired_subscriptions"])],
            ["Total Data Used (GB)", f"{analytics['total_data_used']:.2f}"],
            ["Average Sessions", f"{analytics['average_sessions']:.2f}"],
        ]
        
        table = Table(summary_data)
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
        
        story.append(Paragraph("Summary", styles['Heading2']))
        story.append(table)
        story.append(Spacer(1, 20))

    async def _add_billing_pdf_content(self, story, styles, start_date, end_date, **kwargs):
        """Add billing content to PDF."""
        analytics = await self.get_billing_analytics(start_date, end_date)
        
        # Summary table
        summary_data = [
            ["Metric", "Value"],
            ["Total Invoices", str(analytics["total_invoices"])],
            ["Total Revenue", f"${analytics['total_revenue']:.2f}"],
            ["Paid Invoices", str(analytics["paid_invoices"])],
            ["Pending Invoices", str(analytics["pending_invoices"])],
            ["Overdue Invoices", str(analytics["overdue_invoices"])],
            ["Collection Rate", f"{analytics['collection_rate']:.1f}%"],
            ["Average Invoice Amount", f"${analytics['average_invoice_amount']:.2f}"],
        ]
        
        table = Table(summary_data)
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
        
        story.append(Paragraph("Billing Summary", styles['Heading2']))
        story.append(table)
        story.append(Spacer(1, 20))

    async def _add_router_pdf_content(self, story, styles, start_date, end_date, **kwargs):
        """Add router content to PDF."""
        analytics = await self.get_router_analytics(start_date, end_date)
        
        # Summary table
        summary_data = [
            ["Metric", "Value"],
            ["Total Routers", str(analytics["total_routers"])],
            ["Online Routers", str(analytics["online_routers"])],
            ["Offline Routers", str(analytics["offline_routers"])],
            ["Total Subscriptions", str(analytics["total_subscriptions"])],
            ["Average Uptime", f"{analytics['average_uptime']:.1f} hours"],
        ]
        
        table = Table(summary_data)
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
        
        story.append(Paragraph("Router Summary", styles['Heading2']))
        story.append(table)
        story.append(Spacer(1, 20))

    async def _add_ticket_pdf_content(self, story, styles, start_date, end_date, **kwargs):
        """Add ticket content to PDF."""
        analytics = await self.get_ticket_analytics(start_date, end_date)
        
        # Summary table
        summary_data = [
            ["Metric", "Value"],
            ["Total Tickets", str(analytics["total_tickets"])],
            ["Open Tickets", str(analytics["open_tickets"])],
            ["Resolved Tickets", str(analytics["resolved_tickets"])],
            ["Closed Tickets", str(analytics["closed_tickets"])],
            ["Average Resolution Time", f"{analytics['average_resolution_time']:.1f} hours"],
        ]
        
        table = Table(summary_data)
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
        
        story.append(Paragraph("Support Ticket Summary", styles['Heading2']))
        story.append(table)
        story.append(Spacer(1, 20))

    async def generate_excel_report(
        self,
        report_type: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        **kwargs
    ) -> bytes:
        """Generate Excel report."""
        buffer = io.BytesIO()
        
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            if report_type == "subscriptions":
                await self._add_subscription_excel_content(writer, start_date, end_date, **kwargs)
            elif report_type == "billing":
                await self._add_billing_excel_content(writer, start_date, end_date, **kwargs)
            elif report_type == "routers":
                await self._add_router_excel_content(writer, start_date, end_date, **kwargs)
            elif report_type == "tickets":
                await self._add_ticket_excel_content(writer, start_date, end_date, **kwargs)
        
        buffer.seek(0)
        return buffer.getvalue()

    async def _add_subscription_excel_content(self, writer, start_date, end_date, **kwargs):
        """Add subscription content to Excel."""
        # Get detailed data
        query = select(Subscription).where(
            and_(
                Subscription.created_at >= start_date,
                Subscription.created_at <= end_date
            )
        )
        if kwargs.get('plan_id'):
            query = query.where(Subscription.plan_id == kwargs['plan_id'])
        if kwargs.get('router_id'):
            query = query.where(Subscription.router_id == kwargs['router_id'])

        result = await self.db.execute(query)
        subscriptions = result.scalars().all()

        # Convert to DataFrame
        data = []
        for sub in subscriptions:
            data.append({
                "ID": sub.id,
                "Username": sub.username,
                "Status": sub.status.value,
                "Type": sub.subscription_type.value,
                "Start Date": sub.start_date,
                "End Date": sub.end_date,
                "Data Used (GB)": float(sub.total_data_used_gb),
                "Sessions": sub.session_count,
                "Last Activity": sub.last_activity,
                "Created": sub.created_at,
            })

        if data:
            df = pd.DataFrame(data)
            df.to_excel(writer, sheet_name='Subscriptions', index=False)

        # Add analytics sheet
        analytics = await self.get_subscription_analytics(start_date, end_date, **kwargs)
        analytics_data = [
            ["Metric", "Value"],
            ["Total Subscriptions", analytics["total_subscriptions"]],
            ["Active Subscriptions", analytics["active_subscriptions"]],
            ["Expired Subscriptions", analytics["expired_subscriptions"]],
            ["Total Data Used (GB)", analytics["total_data_used"]],
            ["Average Sessions", analytics["average_sessions"]],
        ]
        analytics_df = pd.DataFrame(analytics_data[1:], columns=analytics_data[0])
        analytics_df.to_excel(writer, sheet_name='Analytics', index=False)

    async def _add_billing_excel_content(self, writer, start_date, end_date, **kwargs):
        """Add billing content to Excel."""
        # Get detailed data
        query = select(Invoice).where(
            and_(
                Invoice.created_at >= start_date,
                Invoice.created_at <= end_date
            )
        )
        result = await self.db.execute(query)
        invoices = result.scalars().all()

        # Convert to DataFrame
        data = []
        for inv in invoices:
            data.append({
                "Invoice Number": inv.invoice_number,
                "User ID": inv.user_id,
                "Subscription ID": inv.subscription_id,
                "Subtotal": float(inv.subtotal),
                "Tax": float(inv.tax_amount),
                "Discount": float(inv.discount_amount),
                "Total": float(inv.total_amount),
                "Paid": float(inv.paid_amount),
                "Balance": float(inv.balance),
                "Status": inv.status.value,
                "Issue Date": inv.issue_date,
                "Due Date": inv.due_date,
                "Paid Date": inv.paid_date,
                "Created": inv.created_at,
            })

        if data:
            df = pd.DataFrame(data)
            df.to_excel(writer, sheet_name='Invoices', index=False)

        # Add analytics sheet
        analytics = await self.get_billing_analytics(start_date, end_date)
        analytics_data = [
            ["Metric", "Value"],
            ["Total Invoices", analytics["total_invoices"]],
            ["Total Revenue", analytics["total_revenue"]],
            ["Paid Invoices", analytics["paid_invoices"]],
            ["Pending Invoices", analytics["pending_invoices"]],
            ["Overdue Invoices", analytics["overdue_invoices"]],
            ["Collection Rate", analytics["collection_rate"]],
            ["Average Invoice Amount", analytics["average_invoice_amount"]],
        ]
        analytics_df = pd.DataFrame(analytics_data[1:], columns=analytics_data[0])
        analytics_df.to_excel(writer, sheet_name='Analytics', index=False)

    async def _add_router_excel_content(self, writer, start_date, end_date, **kwargs):
        """Add router content to Excel."""
        # Get detailed data
        query = select(Router)
        result = await self.db.execute(query)
        routers = result.scalars().all()

        # Convert to DataFrame
        data = []
        for router in routers:
            data.append({
                "ID": router.id,
                "Name": router.name,
                "IP Address": router.ip_address,
                "Status": router.status.value,
                "Type": router.router_type.value,
                "Location": router.location,
                "Uptime": router.uptime,
                "Last Seen": router.last_seen,
                "Created": router.created_at,
            })

        if data:
            df = pd.DataFrame(data)
            df.to_excel(writer, sheet_name='Routers', index=False)

        # Add analytics sheet
        analytics = await self.get_router_analytics(start_date, end_date)
        analytics_data = [
            ["Metric", "Value"],
            ["Total Routers", analytics["total_routers"]],
            ["Online Routers", analytics["online_routers"]],
            ["Offline Routers", analytics["offline_routers"]],
            ["Total Subscriptions", analytics["total_subscriptions"]],
            ["Average Uptime", analytics["average_uptime"]],
        ]
        analytics_df = pd.DataFrame(analytics_data[1:], columns=analytics_data[0])
        analytics_df.to_excel(writer, sheet_name='Analytics', index=False)

    async def _add_ticket_excel_content(self, writer, start_date, end_date, **kwargs):
        """Add ticket content to Excel."""
        # Get detailed data
        query = select(SupportTicket).where(
            and_(
                SupportTicket.created_at >= start_date,
                SupportTicket.created_at <= end_date
            )
        )
        result = await self.db.execute(query)
        tickets = result.scalars().all()

        # Convert to DataFrame
        data = []
        for ticket in tickets:
            data.append({
                "ID": ticket.id,
                "Ticket Number": ticket.ticket_number,
                "User ID": ticket.user_id,
                "Subject": ticket.subject,
                "Status": ticket.status.value,
                "Priority": ticket.priority.value,
                "Category": ticket.category,
                "Assigned To": ticket.assigned_to,
                "Created": ticket.created_at,
                "Resolved": ticket.resolved_at,
                "Closed": ticket.closed_at,
            })

        if data:
            df = pd.DataFrame(data)
            df.to_excel(writer, sheet_name='Tickets', index=False)

        # Add analytics sheet
        analytics = await self.get_ticket_analytics(start_date, end_date)
        analytics_data = [
            ["Metric", "Value"],
            ["Total Tickets", analytics["total_tickets"]],
            ["Open Tickets", analytics["open_tickets"]],
            ["Resolved Tickets", analytics["resolved_tickets"]],
            ["Closed Tickets", analytics["closed_tickets"]],
            ["Average Resolution Time", analytics["average_resolution_time"]],
        ]
        analytics_df = pd.DataFrame(analytics_data[1:], columns=analytics_data[0])
        analytics_df.to_excel(writer, sheet_name='Analytics', index=False)
