import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import logging
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from src.config import (
    THEME_COLORS, THEME_HEX, FONT_TITLE, FONT_BODY, DB_PATH, CHART_PATH, PPTX_PATH
)
from src.analyst import BusinessInsights

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Presenter")

def generate_matplotlib_chart():
    """Queries the Gold summary and creates a clean, premium bar chart of Monthly Revenue."""
    logger.info("Presenter: Creating Matplotlib visual chart...")
    
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}. Run the ETL pipeline first.")
        
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query("SELECT month, revenue FROM gold_monthly_metrics ORDER BY month ASC", conn)
    conn.close()
    
    # Enable modern style
    plt.rcParams['font.family'] = FONT_TITLE
    fig, ax = plt.subplots(figsize=(7, 5), dpi=300)
    fig.patch.set_facecolor(THEME_HEX['light_bg'])
    ax.set_facecolor(THEME_HEX['light_bg'])
    
    # Draw bars with Indigo primary color and clean border rounded aesthetic
    bars = ax.bar(
        df['month'], 
        df['revenue'] / 1000.0, # Scale to thousands
        color=THEME_HEX['primary'], 
        width=0.55, 
        edgecolor=THEME_HEX['primary'],
        alpha=0.9
    )
    
    # Add values on top of the bars
    for bar in bars:
        yval = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width()/2.0, 
            yval + 2, 
            f"${yval:.1f}k", 
            ha='center', 
            va='bottom', 
            fontsize=9, 
            color=THEME_HEX['text_muted'],
            fontweight='bold'
        )
        
    # Styling labels and titles
    ax.set_title("MONTHLY REVENUE OVERVIEW", fontsize=12, fontweight='bold', pad=20, color=THEME_HEX['text_dark'])
    ax.set_ylabel("Revenue (in thousands USD)", fontsize=10, fontweight='bold', color=THEME_HEX['text_muted'])
    ax.set_xlabel("Month (2026)", fontsize=10, fontweight='bold', color=THEME_HEX['text_muted'])
    
    # Adjust ticks
    ax.tick_params(colors=THEME_HEX['text_muted'], labelsize=9)
    
    # Remove outer spines for borderless premium feel
    for spine in ['top', 'right', 'left', 'bottom']:
        ax.spines[spine].set_visible(False)
        
    # Add thin light gridlines for y-axis
    ax.grid(axis='y', linestyle='--', alpha=0.6, color=THEME_HEX['grid_color'])
    ax.set_axisbelow(True) # Keep grid behind bars
    
    plt.tight_layout()
    plt.savefig(CHART_PATH, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()
    
    logger.info(f"Presenter: Chart generated and saved to {CHART_PATH}.")

def apply_text_formatting(paragraph, text, size_pt, color_rgb, font_name, bold=False, italic=False, alignment=PP_ALIGN.LEFT):
    """Utility to safely format paragraphs in python-pptx."""
    paragraph.text = text
    paragraph.font.name = font_name
    paragraph.font.size = Pt(size_pt)
    paragraph.font.color.rgb = RGBColor(*color_rgb)
    paragraph.font.bold = bold
    paragraph.font.italic = italic
    paragraph.alignment = alignment

def add_slide_card(slide, left, top, width, height):
    """Draws a white rounded panel box (dashboard card style) to back the text."""
    card = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height
    )
    card.fill.solid()
    card.fill.fore_color.rgb = RGBColor(*THEME_COLORS['card_bg'])
    card.line.color.rgb = RGBColor(226, 232, 240) # Slate 200 light border
    card.line.width = Pt(1)
    return card

def create_presentation_deck(insights: BusinessInsights):
    """Builds the final 3-slide e-commerce presentation deck using parsed JSON insights."""
    logger.info("Presenter: Compiling PowerPoint deck...")
    
    # Initialize standard presentation
    prs = Presentation()
    
    # Set to 16:9 widescreen layout
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    
    # Use blank slide layouts (usually index 6 in default templates is blank)
    blank_layout = prs.slide_layouts[6]
    
    # ==========================================
    # SLIDE 1: Title Slide (Dark Theme)
    # ==========================================
    slide_1 = prs.slides.add_slide(blank_layout)
    
    # Set dark background fill
    bg_1 = slide_1.background
    fill_1 = bg_1.fill
    fill_1.solid()
    fill_1.fore_color.rgb = RGBColor(*THEME_COLORS['dark_bg'])
    
    # Decorative accent line
    accent_bar = slide_1.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(1.5), Inches(2.2), Inches(0.15), Inches(3.2)
    )
    accent_bar.fill.solid()
    accent_bar.fill.fore_color.rgb = RGBColor(*THEME_COLORS['primary'])
    accent_bar.line.fill.background()
    
    # Title & Subtitle text box
    title_box = slide_1.shapes.add_textbox(Inches(1.8), Inches(2.1), Inches(10.0), Inches(3.5))
    tf_1 = title_box.text_frame
    tf_1.word_wrap = True
    
    # Title Paragraph
    p_title = tf_1.paragraphs[0]
    apply_text_formatting(
        p_title, "E-COMMERCE PERFORMANCE REPORT", 38, THEME_COLORS['card_bg'], FONT_TITLE, bold=True
    )
    p_title.space_after = Pt(14)
    
    # Subtitle Paragraph
    p_sub = tf_1.add_paragraph()
    apply_text_formatting(
        p_sub, "6-Month Sales Auditing & AI-Generated Business Insights", 18, THEME_COLORS['secondary'], FONT_BODY, italic=True
    )
    
    # Metadata Footer
    p_meta = tf_1.add_paragraph()
    p_meta.space_before = Pt(60)
    apply_text_formatting(
        p_meta, f"Generated: {pd.Timestamp.now().strftime('%Y-%m-%d')} | Data Warehouse ETL & SQL Pipeline", 11, THEME_COLORS['text_muted'], FONT_BODY
    )
    
    # ==========================================
    # SLIDE 2: Executive Summary & Key Findings (Light Theme)
    # ==========================================
    slide_2 = prs.slides.add_slide(blank_layout)
    bg_2 = slide_2.background
    fill_2 = bg_2.fill
    fill_2.solid()
    fill_2.fore_color.rgb = RGBColor(*THEME_COLORS['light_bg'])
    
    # Title
    header_2 = slide_2.shapes.add_textbox(Inches(0.8), Inches(0.5), Inches(11.73), Inches(0.8))
    apply_text_formatting(
        header_2.text_frame.paragraphs[0], "Executive Summary & Core Findings", 26, THEME_COLORS['text_dark'], FONT_TITLE, bold=True
    )
    
    # Column 1: Executive Summary Card (Left)
    col_width = Inches(5.6)
    col_gap = Inches(0.53)
    card_height = Inches(5.0)
    
    add_slide_card(slide_2, Inches(0.8), Inches(1.5), col_width, card_height)
    summary_box = slide_2.shapes.add_textbox(Inches(1.0), Inches(1.7), col_width - Inches(0.4), card_height - Inches(0.4))
    tf_summary = summary_box.text_frame
    tf_summary.word_wrap = True
    
    p_sum_head = tf_summary.paragraphs[0]
    apply_text_formatting(p_sum_head, "EXECUTIVE SUMMARY", 14, THEME_COLORS['primary'], FONT_TITLE, bold=True)
    p_sum_head.space_after = Pt(14)
    
    p_sum_body = tf_summary.add_paragraph()
    apply_text_formatting(p_sum_body, insights.executive_summary, 13, THEME_COLORS['text_dark'], FONT_BODY)
    p_sum_body.line_spacing = 1.2
    
    # Column 2: Key Findings Card (Right)
    left_col_2 = Inches(0.8) + col_width + col_gap
    add_slide_card(slide_2, left_col_2, Inches(1.5), col_width, card_height)
    findings_box = slide_2.shapes.add_textbox(left_col_2 + Inches(0.2), Inches(1.7), col_width - Inches(0.4), card_height - Inches(0.4))
    tf_findings = findings_box.text_frame
    tf_findings.word_wrap = True
    
    p_find_head = tf_findings.paragraphs[0]
    apply_text_formatting(p_find_head, "KEY FINDINGS & OBSERVATIONS", 14, THEME_COLORS['primary'], FONT_TITLE, bold=True)
    p_find_head.space_after = Pt(14)
    
    for finding in insights.key_findings:
        p_item = tf_findings.add_paragraph()
        p_item.space_after = Pt(10)
        p_item.level = 0
        p_item.line_spacing = 1.15
        
        # Format bullet point
        apply_text_formatting(p_item, f"•  {finding}", 12, THEME_COLORS['text_dark'], FONT_BODY)
        
    # ==========================================
    # SLIDE 3: Visuals & Recommendations (Light Theme)
    # ==========================================
    slide_3 = prs.slides.add_slide(blank_layout)
    bg_3 = slide_3.background
    fill_3 = bg_3.fill
    fill_3.solid()
    fill_3.fore_color.rgb = RGBColor(*THEME_COLORS['light_bg'])
    
    # Title
    header_3 = slide_3.shapes.add_textbox(Inches(0.8), Inches(0.5), Inches(11.73), Inches(0.8))
    apply_text_formatting(
        header_3.text_frame.paragraphs[0], "Financial Trends & AI Recommendations", 26, THEME_COLORS['text_dark'], FONT_TITLE, bold=True
    )
    
    # Column 1: Matplotlib Chart Card (Left)
    add_slide_card(slide_3, Inches(0.8), Inches(1.5), col_width, card_height)
    
    # Insert visual image inside the card
    slide_3.shapes.add_picture(
        str(CHART_PATH), 
        Inches(1.0), 
        Inches(1.75), 
        width=col_width - Inches(0.4), 
        height=card_height - Inches(0.5)
    )
    
    # Column 2: Actionable Recommendations Card (Right)
    add_slide_card(slide_3, left_col_2, Inches(1.5), col_width, card_height)
    rec_box = slide_3.shapes.add_textbox(left_col_2 + Inches(0.2), Inches(1.7), col_width - Inches(0.4), card_height - Inches(0.4))
    tf_rec = rec_box.text_frame
    tf_rec.word_wrap = True
    
    p_rec_head = tf_rec.paragraphs[0]
    apply_text_formatting(p_rec_head, "RECOMMENDED STRATEGIC ACTIONS", 14, THEME_COLORS['secondary'], FONT_TITLE, bold=True)
    p_rec_head.space_after = Pt(14)
    
    for action in insights.recommended_actions:
        p_action = tf_rec.add_paragraph()
        p_action.space_after = Pt(12)
        p_action.level = 0
        p_action.line_spacing = 1.15
        
        # Format bullet point
        apply_text_formatting(p_action, f"✔  {action}", 12, THEME_COLORS['text_dark'], FONT_BODY)
        
    # Save PPTX
    prs.save(str(PPTX_PATH))
    logger.info(f"Presenter: Presentation saved successfully to {PPTX_PATH}.")
