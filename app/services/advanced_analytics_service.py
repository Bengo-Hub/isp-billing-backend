"""Advanced analytics service with ML forecasting and predictive analytics."""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error
import warnings
warnings.filterwarnings('ignore')

from sqlalchemy import select, func, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.exceptions import ValidationError, ConfigurationError
from app.models.billing import Invoice, Payment, InvoiceStatus, PaymentStatus
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionUsageLog
from app.models.user import User, UserStatus
from app.models.plan import ServicePlan, PlanType
from app.models.router import Router, RouterStatus

logger = get_logger(__name__)


class AdvancedAnalyticsService:
    """Production-ready advanced analytics service with ML forecasting."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)
        
        # ML model configuration
        self.forecast_models = {
            'linear': LinearRegression(),
            'random_forest': RandomForestRegressor(n_estimators=100, random_state=42)
        }
        self.scaler = StandardScaler()
        
        # Analytics configuration
        self.min_data_points = 30  # Minimum data points for forecasting
        self.forecast_periods = [30, 60, 90]  # Days to forecast
        self.confidence_threshold = 0.7  # Minimum confidence for predictions

    async def generate_revenue_forecast(
        self, 
        forecast_days: int = 90,
        model_type: str = "random_forest"
    ) -> Dict[str, Any]:
        """Generate ML-powered revenue forecast."""
        try:
            # Get historical revenue data
            historical_data = await self._get_historical_revenue_data()
            
            if len(historical_data) < self.min_data_points:
                return {
                    "forecast_available": False,
                    "reason": f"Insufficient data. Need at least {self.min_data_points} data points, have {len(historical_data)}",
                    "historical_days": len(historical_data)
                }
            
            # Prepare data for ML model
            X, y = self._prepare_revenue_data(historical_data)
            
            # Select and train model
            if model_type not in self.forecast_models:
                model_type = "random_forest"
            
            model = self.forecast_models[model_type]
            
            # Scale features
            X_scaled = self.scaler.fit_transform(X)
            
            # Train model
            model.fit(X_scaled, y)
            
            # Generate predictions
            forecast_data = self._generate_forecast_data(forecast_days)
            X_forecast = self.scaler.transform(forecast_data)
            predictions = model.predict(X_forecast)
            
            # Calculate confidence metrics
            y_pred_train = model.predict(X_scaled)
            mae = mean_absolute_error(y, y_pred_train)
            rmse = np.sqrt(mean_squared_error(y, y_pred_train))
            confidence = max(0, min(1, 1 - (mae / np.mean(y))))
            
            # Generate forecast periods
            base_date = datetime.utcnow().date()
            forecast_periods = []
            
            for i, prediction in enumerate(predictions):
                forecast_date = base_date + timedelta(days=i+1)
                forecast_periods.append({
                    "date": forecast_date.isoformat(),
                    "predicted_revenue": float(max(0, prediction)),
                    "confidence": float(confidence)
                })
            
            # Calculate summary statistics
            total_forecast = sum(predictions)
            avg_daily_forecast = total_forecast / len(predictions)
            
            # Get current period comparison
            current_period_revenue = await self._get_current_period_revenue(forecast_days)
            growth_rate = ((total_forecast - current_period_revenue) / current_period_revenue * 100) if current_period_revenue > 0 else 0
            
            return {
                "forecast_available": True,
                "model_type": model_type,
                "forecast_days": forecast_days,
                "confidence_score": float(confidence),
                "summary": {
                    "total_forecast_revenue": float(total_forecast),
                    "average_daily_revenue": float(avg_daily_forecast),
                    "current_period_revenue": float(current_period_revenue),
                    "predicted_growth_rate": float(growth_rate)
                },
                "forecast_periods": forecast_periods,
                "model_metrics": {
                    "mean_absolute_error": float(mae),
                    "root_mean_square_error": float(rmse),
                    "training_data_points": len(historical_data)
                },
                "generated_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Revenue forecast generation failed: {e}")
            return {
                "forecast_available": False,
                "error": str(e),
                "generated_at": datetime.utcnow().isoformat()
            }

    async def calculate_customer_retention_rate(
        self, 
        period_months: int = 6
    ) -> Dict[str, Any]:
        """Calculate customer retention rate with cohort analysis."""
        try:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=period_months * 30)
            
            # Get user cohorts by registration month
            cohort_data = await self._get_user_cohorts(start_date, end_date)
            
            # Calculate retention rates for each cohort
            retention_analysis = []
            overall_retention_rates = []
            
            for cohort in cohort_data:
                cohort_retention = await self._calculate_cohort_retention(cohort)
                retention_analysis.append(cohort_retention)
                
                if cohort_retention["retention_rate"] is not None:
                    overall_retention_rates.append(cohort_retention["retention_rate"])
            
            # Calculate overall metrics
            avg_retention_rate = np.mean(overall_retention_rates) if overall_retention_rates else 0
            retention_trend = self._calculate_retention_trend(retention_analysis)
            
            # Identify at-risk customers
            at_risk_customers = await self._identify_at_risk_customers()
            
            return {
                "period_months": period_months,
                "overall_retention_rate": float(avg_retention_rate),
                "retention_trend": retention_trend,
                "cohort_analysis": retention_analysis,
                "at_risk_customers": {
                    "count": len(at_risk_customers),
                    "percentage": len(at_risk_customers) / len(cohort_data) * 100 if cohort_data else 0,
                    "customers": at_risk_customers[:10]  # Return first 10
                },
                "recommendations": self._generate_retention_recommendations(avg_retention_rate, retention_trend),
                "calculated_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Customer retention calculation failed: {e}")
            return {
                "error": str(e),
                "calculated_at": datetime.utcnow().isoformat()
            }

    async def analyze_package_performance(self) -> Dict[str, Any]:
        """Analyze package performance with recommendations."""
        try:
            # Get package usage statistics
            result = await self.db.execute(
                select(
                    ServicePlan.id,
                    ServicePlan.name,
                    ServicePlan.plan_type,
                    func.count(Subscription.id).label('total_subscriptions'),
                    func.count(
                        func.nullif(Subscription.status, SubscriptionStatus.CANCELLED)
                    ).label('active_subscriptions'),
                    func.avg(
                        func.extract('epoch', Subscription.updated_at - Subscription.created_at) / 86400
                    ).label('avg_lifetime_days'),
                    func.sum(Invoice.amount).label('total_revenue')
                )
                .outerjoin(Subscription, ServicePlan.id == Subscription.plan_id)
                .outerjoin(Invoice, Subscription.user_id == Invoice.user_id)
                .group_by(ServicePlan.id, ServicePlan.name, ServicePlan.plan_type)
                .order_by(func.count(Subscription.id).desc())
            )
            
            packages = result.all()
            
            # Analyze each package
            package_analysis = []
            for package in packages:
                # Calculate metrics
                subscription_rate = (package.active_subscriptions / package.total_subscriptions * 100) if package.total_subscriptions > 0 else 0
                avg_revenue_per_user = (package.total_revenue / package.total_subscriptions) if package.total_subscriptions > 0 else 0
                
                # Determine performance category
                if subscription_rate >= 80 and avg_revenue_per_user > 1000:
                    performance = "excellent"
                elif subscription_rate >= 60 and avg_revenue_per_user > 500:
                    performance = "good"
                elif subscription_rate >= 40:
                    performance = "average"
                else:
                    performance = "poor"
                
                package_analysis.append({
                    "package_id": package.id,
                    "package_name": package.name,
                    "package_type": package.plan_type.value if package.plan_type else "unknown",
                    "total_subscriptions": package.total_subscriptions or 0,
                    "active_subscriptions": package.active_subscriptions or 0,
                    "subscription_rate": float(subscription_rate),
                    "average_lifetime_days": float(package.avg_lifetime_days or 0),
                    "total_revenue": float(package.total_revenue or 0),
                    "average_revenue_per_user": float(avg_revenue_per_user),
                    "performance_category": performance
                })
            
            # Generate insights and recommendations
            insights = self._generate_package_insights(package_analysis)
            
            return {
                "packages": package_analysis,
                "insights": insights,
                "summary": {
                    "total_packages": len(package_analysis),
                    "excellent_packages": len([p for p in package_analysis if p["performance_category"] == "excellent"]),
                    "good_packages": len([p for p in package_analysis if p["performance_category"] == "good"]),
                    "average_packages": len([p for p in package_analysis if p["performance_category"] == "average"]),
                    "poor_packages": len([p for p in package_analysis if p["performance_category"] == "poor"])
                },
                "analyzed_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Package performance analysis failed: {e}")
            return {
                "error": str(e),
                "analyzed_at": datetime.utcnow().isoformat()
            }

    async def analyze_network_usage_patterns(self, days: int = 30) -> Dict[str, Any]:
        """Analyze network usage patterns and trends."""
        try:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)
            
            # Get usage data from subscription logs
            result = await self.db.execute(
                select(
                    SubscriptionUsageLog.log_date,
                    SubscriptionUsageLog.subscription_type,
                    func.sum(SubscriptionUsageLog.bytes_downloaded).label('total_download'),
                    func.sum(SubscriptionUsageLog.bytes_uploaded).label('total_upload'),
                    func.count(SubscriptionUsageLog.id).label('session_count'),
                    func.avg(SubscriptionUsageLog.session_duration).label('avg_session_duration')
                )
                .where(SubscriptionUsageLog.log_date >= start_date.date())
                .group_by(
                    SubscriptionUsageLog.log_date,
                    SubscriptionUsageLog.subscription_type
                )
                .order_by(SubscriptionUsageLog.log_date)
            )
            
            usage_data = result.all()
            
            # Process data for analysis
            daily_usage = {}
            type_usage = {"hotspot": [], "pppoe": []}
            
            for record in usage_data:
                date_str = record.log_date.isoformat()
                
                if date_str not in daily_usage:
                    daily_usage[date_str] = {
                        "download_gb": 0,
                        "upload_gb": 0,
                        "total_sessions": 0,
                        "avg_session_minutes": 0
                    }
                
                # Convert bytes to GB
                download_gb = (record.total_download or 0) / (1024**3)
                upload_gb = (record.total_upload or 0) / (1024**3)
                
                daily_usage[date_str]["download_gb"] += download_gb
                daily_usage[date_str]["upload_gb"] += upload_gb
                daily_usage[date_str]["total_sessions"] += record.session_count or 0
                daily_usage[date_str]["avg_session_minutes"] = record.avg_session_duration or 0
                
                # Track by subscription type
                if record.subscription_type:
                    type_usage[record.subscription_type.value].append({
                        "date": date_str,
                        "download_gb": download_gb,
                        "upload_gb": upload_gb,
                        "sessions": record.session_count or 0
                    })
            
            # Calculate trends and patterns
            usage_trend = self._calculate_usage_trend(daily_usage)
            peak_usage_analysis = self._analyze_peak_usage(daily_usage)
            type_comparison = self._compare_subscription_types(type_usage)
            
            # Generate usage insights
            insights = self._generate_usage_insights(daily_usage, usage_trend, peak_usage_analysis)
            
            return {
                "period_days": days,
                "daily_usage": daily_usage,
                "usage_trend": usage_trend,
                "peak_usage_analysis": peak_usage_analysis,
                "subscription_type_comparison": type_comparison,
                "insights": insights,
                "summary": {
                    "total_download_gb": sum(day["download_gb"] for day in daily_usage.values()),
                    "total_upload_gb": sum(day["upload_gb"] for day in daily_usage.values()),
                    "total_sessions": sum(day["total_sessions"] for day in daily_usage.values()),
                    "average_daily_download": np.mean([day["download_gb"] for day in daily_usage.values()]) if daily_usage else 0,
                    "average_daily_upload": np.mean([day["upload_gb"] for day in daily_usage.values()]) if daily_usage else 0
                },
                "analyzed_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Network usage analysis failed: {e}")
            return {
                "error": str(e),
                "analyzed_at": datetime.utcnow().isoformat()
            }

    async def predict_customer_churn(self) -> Dict[str, Any]:
        """Predict customer churn using ML algorithms."""
        try:
            # Get customer data for churn analysis
            customers_data = await self._get_customer_churn_data()
            
            if len(customers_data) < self.min_data_points:
                return {
                    "prediction_available": False,
                    "reason": f"Insufficient customer data for churn prediction",
                    "customer_count": len(customers_data)
                }
            
            # Prepare features for churn prediction
            features, labels, customer_ids = self._prepare_churn_data(customers_data)
            
            # Train churn prediction model
            churn_model = RandomForestRegressor(n_estimators=100, random_state=42)
            churn_model.fit(features, labels)
            
            # Predict churn probability
            churn_probabilities = churn_model.predict(features)
            
            # Identify high-risk customers
            high_risk_customers = []
            medium_risk_customers = []
            
            for i, (customer_id, prob) in enumerate(zip(customer_ids, churn_probabilities)):
                customer_data = customers_data[i]
                
                if prob > 0.7:
                    high_risk_customers.append({
                        "customer_id": customer_id,
                        "churn_probability": float(prob),
                        "risk_factors": self._identify_risk_factors(customer_data),
                        "recommended_actions": self._recommend_retention_actions(customer_data, prob)
                    })
                elif prob > 0.4:
                    medium_risk_customers.append({
                        "customer_id": customer_id,
                        "churn_probability": float(prob),
                        "risk_factors": self._identify_risk_factors(customer_data)
                    })
            
            # Calculate overall churn metrics
            avg_churn_probability = np.mean(churn_probabilities)
            predicted_churn_count = len([p for p in churn_probabilities if p > 0.5])
            
            return {
                "prediction_available": True,
                "model_confidence": float(1 - mean_absolute_error(labels, churn_probabilities)),
                "summary": {
                    "total_customers_analyzed": len(customers_data),
                    "average_churn_probability": float(avg_churn_probability),
                    "predicted_churn_count": predicted_churn_count,
                    "high_risk_customers": len(high_risk_customers),
                    "medium_risk_customers": len(medium_risk_customers)
                },
                "high_risk_customers": high_risk_customers,
                "medium_risk_customers": medium_risk_customers[:20],  # Limit to 20
                "recommendations": self._generate_churn_prevention_strategy(high_risk_customers),
                "predicted_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Customer churn prediction failed: {e}")
            return {
                "prediction_available": False,
                "error": str(e),
                "predicted_at": datetime.utcnow().isoformat()
            }

    async def _get_historical_revenue_data(self, days: int = 365) -> List[Dict[str, Any]]:
        """Get historical revenue data for forecasting."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        result = await self.db.execute(
            select(
                func.date(Payment.created_at).label('payment_date'),
                func.sum(Payment.amount).label('daily_revenue'),
                func.count(Payment.id).label('transaction_count')
            )
            .where(
                and_(
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.created_at >= start_date
                )
            )
            .group_by(func.date(Payment.created_at))
            .order_by(func.date(Payment.created_at))
        )
        
        return [
            {
                "date": record.payment_date,
                "revenue": float(record.daily_revenue or 0),
                "transactions": record.transaction_count or 0
            }
            for record in result
        ]

    def _prepare_revenue_data(self, historical_data: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare revenue data for ML model."""
        # Create features: day_of_week, day_of_month, month, transaction_count, previous_days_revenue
        features = []
        targets = []
        
        for i, record in enumerate(historical_data):
            date = record["date"]
            revenue = record["revenue"]
            transactions = record["transactions"]
            
            # Create feature vector
            feature_vector = [
                date.weekday(),  # Day of week (0-6)
                date.day,        # Day of month (1-31)
                date.month,      # Month (1-12)
                transactions,    # Number of transactions
            ]
            
            # Add rolling averages if enough data
            if i >= 7:
                week_avg = np.mean([historical_data[j]["revenue"] for j in range(i-6, i+1)])
                feature_vector.append(week_avg)
            else:
                feature_vector.append(revenue)
            
            if i >= 30:
                month_avg = np.mean([historical_data[j]["revenue"] for j in range(i-29, i+1)])
                feature_vector.append(month_avg)
            else:
                feature_vector.append(revenue)
            
            features.append(feature_vector)
            targets.append(revenue)
        
        return np.array(features), np.array(targets)

    def _generate_forecast_data(self, forecast_days: int) -> np.ndarray:
        """Generate feature data for forecasting."""
        base_date = datetime.utcnow().date()
        forecast_features = []
        
        for i in range(forecast_days):
            forecast_date = base_date + timedelta(days=i+1)
            
            # Create feature vector for forecast date
            feature_vector = [
                forecast_date.weekday(),  # Day of week
                forecast_date.day,        # Day of month
                forecast_date.month,      # Month
                20,  # Estimated transactions (could be improved with historical average)
                1000,  # Estimated week average (placeholder)
                1000   # Estimated month average (placeholder)
            ]
            
            forecast_features.append(feature_vector)
        
        return np.array(forecast_features)

    async def _get_current_period_revenue(self, days: int) -> float:
        """Get revenue for the current period."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        result = await self.db.execute(
            select(func.sum(Payment.amount))
            .where(
                and_(
                    Payment.status == PaymentStatus.COMPLETED,
                    Payment.created_at >= start_date
                )
            )
        )
        
        return float(result.scalar() or 0)

    async def _get_user_cohorts(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """Get user cohorts for retention analysis."""
        result = await self.db.execute(
            select(
                func.date_trunc('month', User.created_at).label('cohort_month'),
                func.count(User.id).label('cohort_size'),
                func.array_agg(User.id).label('user_ids')
            )
            .where(User.created_at.between(start_date, end_date))
            .group_by(func.date_trunc('month', User.created_at))
            .order_by(func.date_trunc('month', User.created_at))
        )
        
        return [
            {
                "cohort_month": record.cohort_month,
                "cohort_size": record.cohort_size,
                "user_ids": record.user_ids
            }
            for record in result
        ]

    async def _calculate_cohort_retention(self, cohort: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate retention rate for a cohort."""
        cohort_month = cohort["cohort_month"]
        user_ids = cohort["user_ids"]
        
        # Calculate retention for different periods
        periods = [30, 60, 90, 180]  # days
        retention_rates = {}
        
        for period in periods:
            retention_date = cohort_month + timedelta(days=period)
            
            # Count active users in the period
            result = await self.db.execute(
                select(func.count(Subscription.user_id.distinct()))
                .where(
                    and_(
                        Subscription.user_id.in_(user_ids),
                        Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.SUSPENDED]),
                        Subscription.created_at <= retention_date
                    )
                )
            )
            
            active_users = result.scalar() or 0
            retention_rate = (active_users / cohort["cohort_size"] * 100) if cohort["cohort_size"] > 0 else 0
            retention_rates[f"day_{period}"] = float(retention_rate)
        
        return {
            "cohort_month": cohort_month.isoformat(),
            "cohort_size": cohort["cohort_size"],
            "retention_rates": retention_rates,
            "retention_rate": retention_rates.get("day_90")  # Use 90-day as primary metric
        }

    def _calculate_retention_trend(self, retention_analysis: List[Dict[str, Any]]) -> str:
        """Calculate retention trend direction."""
        if len(retention_analysis) < 3:
            return "insufficient_data"
        
        # Get recent retention rates
        recent_rates = [
            analysis["retention_rate"] 
            for analysis in retention_analysis[-3:] 
            if analysis["retention_rate"] is not None
        ]
        
        if len(recent_rates) < 2:
            return "insufficient_data"
        
        # Calculate trend
        if recent_rates[-1] > recent_rates[0] * 1.05:
            return "improving"
        elif recent_rates[-1] < recent_rates[0] * 0.95:
            return "declining"
        else:
            return "stable"

    async def _identify_at_risk_customers(self) -> List[Dict[str, Any]]:
        """Identify customers at risk of churning."""
        # Get customers with concerning patterns
        result = await self.db.execute(
            select(
                User.id,
                User.username,
                User.email,
                func.max(Subscription.expires_at).label('last_subscription_end'),
                func.count(Invoice.id).label('overdue_invoices'),
                func.max(User.last_login).label('last_login')
            )
            .outerjoin(Subscription, User.id == Subscription.user_id)
            .outerjoin(Invoice, and_(
                User.id == Invoice.user_id,
                Invoice.status == InvoiceStatus.OVERDUE
            ))
            .group_by(User.id, User.username, User.email)
            .having(
                or_(
                    func.count(Invoice.id) > 0,  # Has overdue invoices
                    func.max(User.last_login) < datetime.utcnow() - timedelta(days=30)  # Inactive
                )
            )
        )
        
        at_risk = []
        for record in result:
            risk_score = 0
            risk_factors = []
            
            # Calculate risk based on various factors
            if record.overdue_invoices > 0:
                risk_score += 30
                risk_factors.append(f"{record.overdue_invoices} overdue invoices")
            
            if record.last_login and (datetime.utcnow() - record.last_login).days > 30:
                risk_score += 25
                risk_factors.append("Inactive for 30+ days")
            
            if record.last_subscription_end and record.last_subscription_end < datetime.utcnow():
                risk_score += 20
                risk_factors.append("Subscription expired")
            
            at_risk.append({
                "customer_id": record.id,
                "username": record.username,
                "email": record.email,
                "risk_score": risk_score,
                "risk_factors": risk_factors,
                "last_login": record.last_login.isoformat() if record.last_login else None,
                "overdue_invoices": record.overdue_invoices
            })
        
        # Sort by risk score
        return sorted(at_risk, key=lambda x: x["risk_score"], reverse=True)

    async def _get_customer_churn_data(self) -> List[Dict[str, Any]]:
        """Get customer data for churn analysis."""
        # This would get comprehensive customer data including:
        # - Payment history
        # - Usage patterns
        # - Support ticket history
        # - Login frequency
        # - Subscription changes
        
        result = await self.db.execute(
            select(
                User.id,
                User.created_at,
                User.last_login,
                func.count(Subscription.id).label('total_subscriptions'),
                func.count(Invoice.id).label('total_invoices'),
                func.count(Payment.id).label('total_payments'),
                func.avg(Payment.amount).label('avg_payment'),
                func.max(Subscription.expires_at).label('last_subscription_end')
            )
            .outerjoin(Subscription, User.id == Subscription.user_id)
            .outerjoin(Invoice, User.id == Invoice.user_id)
            .outerjoin(Payment, User.id == Payment.user_id)
            .group_by(User.id, User.created_at, User.last_login)
        )
        
        customers = []
        for record in result:
            # Calculate features for churn prediction
            days_since_registration = (datetime.utcnow() - record.created_at).days
            days_since_last_login = (datetime.utcnow() - record.last_login).days if record.last_login else 999
            
            customers.append({
                "customer_id": record.id,
                "days_since_registration": days_since_registration,
                "days_since_last_login": days_since_last_login,
                "total_subscriptions": record.total_subscriptions or 0,
                "total_invoices": record.total_invoices or 0,
                "total_payments": record.total_payments or 0,
                "avg_payment": float(record.avg_payment or 0),
                "subscription_active": record.last_subscription_end and record.last_subscription_end > datetime.utcnow()
            })
        
        return customers

    def _prepare_churn_data(self, customers_data: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray, List[int]]:
        """Prepare customer data for churn prediction."""
        features = []
        labels = []
        customer_ids = []
        
        for customer in customers_data:
            # Create feature vector
            feature_vector = [
                customer["days_since_registration"],
                customer["days_since_last_login"],
                customer["total_subscriptions"],
                customer["total_invoices"],
                customer["total_payments"],
                customer["avg_payment"],
                1 if customer["subscription_active"] else 0
            ]
            
            # Create label (1 for churned, 0 for retained)
            # Simple heuristic: churned if inactive for 60+ days or no active subscription
            churned = (
                customer["days_since_last_login"] > 60 or 
                not customer["subscription_active"]
            )
            
            features.append(feature_vector)
            labels.append(1 if churned else 0)
            customer_ids.append(customer["customer_id"])
        
        return np.array(features), np.array(labels), customer_ids

    def _calculate_usage_trend(self, daily_usage: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate usage trend over time."""
        if len(daily_usage) < 7:
            return {"trend": "insufficient_data"}
        
        # Extract daily download values
        dates = sorted(daily_usage.keys())
        downloads = [daily_usage[date]["download_gb"] for date in dates]
        uploads = [daily_usage[date]["upload_gb"] for date in dates]
        
        # Calculate trend using linear regression
        x = np.arange(len(downloads)).reshape(-1, 1)
        
        # Download trend
        download_model = LinearRegression().fit(x, downloads)
        download_slope = download_model.coef_[0]
        
        # Upload trend
        upload_model = LinearRegression().fit(x, uploads)
        upload_slope = upload_model.coef_[0]
        
        # Determine trend direction
        download_trend = "increasing" if download_slope > 0.1 else "decreasing" if download_slope < -0.1 else "stable"
        upload_trend = "increasing" if upload_slope > 0.1 else "decreasing" if upload_slope < -0.1 else "stable"
        
        return {
            "download_trend": download_trend,
            "upload_trend": upload_trend,
            "download_slope": float(download_slope),
            "upload_slope": float(upload_slope),
            "overall_trend": download_trend if abs(download_slope) > abs(upload_slope) else upload_trend
        }

    def _analyze_peak_usage(self, daily_usage: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze peak usage patterns."""
        if not daily_usage:
            return {}
        
        # Find peak usage days
        sorted_days = sorted(
            daily_usage.items(), 
            key=lambda x: x[1]["download_gb"] + x[1]["upload_gb"], 
            reverse=True
        )
        
        peak_days = sorted_days[:5]  # Top 5 peak days
        
        # Analyze patterns
        peak_weekdays = [datetime.fromisoformat(day[0]).weekday() for day, _ in peak_days]
        most_common_weekday = max(set(peak_weekdays), key=peak_weekdays.count) if peak_weekdays else 0
        
        weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        
        return {
            "peak_days": [
                {
                    "date": day,
                    "total_usage_gb": usage["download_gb"] + usage["upload_gb"],
                    "download_gb": usage["download_gb"],
                    "upload_gb": usage["upload_gb"],
                    "sessions": usage["total_sessions"]
                }
                for day, usage in peak_days
            ],
            "peak_weekday": weekday_names[most_common_weekday],
            "average_peak_usage": np.mean([
                usage["download_gb"] + usage["upload_gb"] 
                for _, usage in peak_days
            ]) if peak_days else 0
        }

    def _compare_subscription_types(self, type_usage: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Compare usage between subscription types."""
        comparison = {}
        
        for sub_type, usage_data in type_usage.items():
            if usage_data:
                total_download = sum(day["download_gb"] for day in usage_data)
                total_upload = sum(day["upload_gb"] for day in usage_data)
                total_sessions = sum(day["sessions"] for day in usage_data)
                
                comparison[sub_type] = {
                    "total_download_gb": total_download,
                    "total_upload_gb": total_upload,
                    "total_sessions": total_sessions,
                    "avg_daily_download": total_download / len(usage_data),
                    "avg_daily_upload": total_upload / len(usage_data),
                    "avg_daily_sessions": total_sessions / len(usage_data)
                }
        
        return comparison

    def _generate_package_insights(self, package_analysis: List[Dict[str, Any]]) -> List[str]:
        """Generate insights from package performance analysis."""
        insights = []
        
        if not package_analysis:
            return ["No package data available for analysis"]
        
        # Top performing packages
        excellent_packages = [p for p in package_analysis if p["performance_category"] == "excellent"]
        if excellent_packages:
            top_package = max(excellent_packages, key=lambda x: x["total_revenue"])
            insights.append(f"Top performer: {top_package['package_name']} with {top_package['total_subscriptions']} subscriptions")
        
        # Underperforming packages
        poor_packages = [p for p in package_analysis if p["performance_category"] == "poor"]
        if poor_packages:
            insights.append(f"{len(poor_packages)} packages are underperforming and may need review")
        
        # Revenue concentration
        total_revenue = sum(p["total_revenue"] for p in package_analysis)
        if package_analysis:
            top_3_revenue = sum(sorted([p["total_revenue"] for p in package_analysis], reverse=True)[:3])
            concentration = (top_3_revenue / total_revenue * 100) if total_revenue > 0 else 0
            
            if concentration > 70:
                insights.append(f"Revenue is highly concentrated: top 3 packages generate {concentration:.1f}% of revenue")
        
        return insights

    def _generate_usage_insights(
        self, 
        daily_usage: Dict[str, Dict[str, Any]], 
        usage_trend: Dict[str, Any], 
        peak_analysis: Dict[str, Any]
    ) -> List[str]:
        """Generate insights from usage analysis."""
        insights = []
        
        if usage_trend.get("overall_trend") == "increasing":
            insights.append("Network usage is trending upward - consider capacity planning")
        elif usage_trend.get("overall_trend") == "decreasing":
            insights.append("Network usage is declining - investigate customer satisfaction")
        
        if peak_analysis.get("peak_weekday"):
            insights.append(f"Peak usage typically occurs on {peak_analysis['peak_weekday']}s")
        
        # Calculate average usage
        if daily_usage:
            avg_daily_download = np.mean([day["download_gb"] for day in daily_usage.values()])
            if avg_daily_download > 100:
                insights.append("High daily download usage detected - monitor bandwidth capacity")
        
        return insights

    def _identify_risk_factors(self, customer_data: Dict[str, Any]) -> List[str]:
        """Identify risk factors for customer churn."""
        risk_factors = []
        
        if customer_data["days_since_last_login"] > 30:
            risk_factors.append("Inactive for extended period")
        
        if customer_data["total_payments"] < customer_data["total_invoices"]:
            risk_factors.append("Payment issues")
        
        if not customer_data["subscription_active"]:
            risk_factors.append("No active subscription")
        
        if customer_data["avg_payment"] < 500:
            risk_factors.append("Low value customer")
        
        return risk_factors

    def _recommend_retention_actions(self, customer_data: Dict[str, Any], churn_prob: float) -> List[str]:
        """Recommend actions to retain at-risk customers."""
        actions = []
        
        if churn_prob > 0.8:
            actions.append("Immediate personal outreach recommended")
            actions.append("Offer special discount or package upgrade")
        
        if customer_data["days_since_last_login"] > 30:
            actions.append("Send re-engagement email campaign")
        
        if not customer_data["subscription_active"]:
            actions.append("Offer renewal incentive")
        
        if customer_data["avg_payment"] < 500:
            actions.append("Suggest more suitable package")
        
        return actions

    def _generate_churn_prevention_strategy(self, high_risk_customers: List[Dict[str, Any]]) -> List[str]:
        """Generate overall churn prevention strategy."""
        if not high_risk_customers:
            return ["Customer retention is healthy - continue monitoring"]
        
        strategies = []
        
        if len(high_risk_customers) > 10:
            strategies.append("High churn risk detected - implement proactive retention program")
        
        # Analyze common risk factors
        all_risk_factors = []
        for customer in high_risk_customers:
            all_risk_factors.extend(customer.get("risk_factors", []))
        
        if "Payment issues" in all_risk_factors:
            strategies.append("Implement flexible payment options and reminders")
        
        if "Inactive for extended period" in all_risk_factors:
            strategies.append("Create re-engagement campaigns for inactive users")
        
        strategies.append("Consider loyalty programs for high-value customers")
        
        return strategies