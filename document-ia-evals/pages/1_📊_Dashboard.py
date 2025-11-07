"""Dashboard page with interactive visualizations."""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from document_ia_evals.utils.config import Config

# Page configuration
st.set_page_config(
    page_title=f"Dashboard | {Config.APP_TITLE}",
    page_icon="📊",
    layout=Config.LAYOUT
)


def generate_sample_data():
    """Generate sample data for demonstration."""
    dates = pd.date_range(
        start=datetime.now() - timedelta(days=30),
        end=datetime.now(),
        freq='D'
    )
    
    df = pd.DataFrame({
        'date': dates,
        'sales': np.random.randint(100, 500, len(dates)),
        'visitors': np.random.randint(1000, 5000, len(dates)),
        'conversion_rate': np.random.uniform(2, 8, len(dates))
    })
    
    return df


def main():
    """Main dashboard page function."""
    # Render sidebar
    sidebar_settings = render_sidebar()
    
    # Page header
    st.title("📊 Dashboard")
    st.markdown("Interactive analytics and visualizations")
    
    # # Metrics row
    # st.subheader("Key Metrics")
    # col1, col2, col3, col4 = st.columns(4)
    
    # with col1:
    #     st.metric(
    #         label="Total Sales",
    #         value="$52,489",
    #         delta="12.5%"
    #     )
    
    # with col2:
    #     st.metric(
    #         label="Visitors",
    #         value="89,234",
    #         delta="-2.3%"
    #     )
    
    # with col3:
    #     st.metric(
    #         label="Conversion Rate",
    #         value="4.8%",
    #         delta="0.5%"
    #     )
    
    # with col4:
    #     st.metric(
    #         label="Avg Order Value",
    #         value="$127",
    #         delta="5.2%"
    #     )
    
    # st.markdown("---")
    
    # # Generate sample data
    # df = generate_sample_data()
    
    # # Charts
    # col1, col2 = st.columns(2)
    
    # with col1:
    #     st.subheader("Sales Trend")
    #     fig_sales = px.line(
    #         df,
    #         x='date',
    #         y='sales',
    #         title='Daily Sales (Last 30 Days)',
    #         labels={'sales': 'Sales ($)', 'date': 'Date'}
    #     )
    #     fig_sales.update_traces(line_color='#1f77b4', line_width=2)
    #     st.plotly_chart(fig_sales, use_container_width=True)
    
    # with col2:
    #     st.subheader("Visitor Analytics")
    #     fig_visitors = px.area(
    #         df,
    #         x='date',
    #         y='visitors',
    #         title='Daily Visitors (Last 30 Days)',
    #         labels={'visitors': 'Visitors', 'date': 'Date'}
    #     )
    #     fig_visitors.update_traces(fillcolor='rgba(31, 119, 180, 0.3)')
    #     st.plotly_chart(fig_visitors, use_container_width=True)
    
    # # Conversion rate chart
    # st.subheader("Conversion Rate Trend")
    # fig_conversion = go.Figure()
    # fig_conversion.add_trace(go.Scatter(
    #     x=df['date'],
    #     y=df['conversion_rate'],
    #     mode='lines+markers',
    #     name='Conversion Rate',
    #     line=dict(color='#2ca02c', width=2),
    #     marker=dict(size=6)
    # ))
    # fig_conversion.update_layout(
    #     title='Conversion Rate Over Time',
    #     xaxis_title='Date',
    #     yaxis_title='Conversion Rate (%)',
    #     hovermode='x unified'
    # )
    # st.plotly_chart(fig_conversion, use_container_width=True)
    
    # # Data table
    # with st.expander("View Raw Data"):
    #     st.dataframe(df, use_container_width=True)


if __name__ == "__main__":
    main()