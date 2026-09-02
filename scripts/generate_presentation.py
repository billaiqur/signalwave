"""
Generate a Signalwave Architecture & Flow PowerPoint presentation.
Run: python scripts/generate_presentation.py
Output: scripts/Signalwave_Presentation.pptx
"""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
import os

# ── Colour Palette ──────────────────────────────────────────────────────────
INDIGO       = RGBColor(0x5B, 0x4F, 0xD1)
INDIGO_DEEP  = RGBColor(0x4A, 0x3F, 0xBD)
INDIGO_LIGHT = RGBColor(0xF0, 0xEE, 0xFC)
POSITIVE     = RGBColor(0x1F, 0xA9, 0x71)
NEGATIVE     = RGBColor(0xE0, 0x52, 0x4A)
NEUTRAL      = RGBColor(0xC9, 0x8A, 0x1F)
DARK         = RGBColor(0x16, 0x1A, 0x2C)
SOFT         = RGBColor(0x6B, 0x70, 0x86)
WHITE        = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_BG     = RGBColor(0xF5, 0xF5, 0xF8)
CARD_BG      = RGBColor(0xFF, 0xFF, 0xFF)
BORDER       = RGBColor(0xE7, 0xE7, 0xEE)
YT_RED       = RGBColor(0xE0, 0x52, 0x4A)
FB_BLUE      = RGBColor(0x18, 0x77, 0xF2)
IG_PURPLE    = RGBColor(0x83, 0x3A, 0xB4)
GOOGLE_BLUE  = RGBColor(0x42, 0x85, 0xF4)


def set_bg(slide, color: RGBColor):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_rect(slide, l, t, w, h, fill_color=None, border_color=None, border_width=Pt(1)):
    shape = slide.shapes.add_shape(1, Inches(l), Inches(t), Inches(w), Inches(h))
    if fill_color:
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill_color
    else:
        shape.fill.background()
    if border_color:
        shape.line.color.rgb = border_color
        shape.line.width = border_width
    else:
        shape.line.fill.background()
    return shape


def add_text_box(slide, text, l, t, w, h,
                 font_size=Pt(14), bold=False, color=DARK,
                 align=PP_ALIGN.LEFT, wrap=True, italic=False):
    txBox = slide.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    txBox.word_wrap = wrap
    tf = txBox.text_frame
    tf.word_wrap = wrap
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = font_size
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    return txBox


def add_label_box(slide, text, l, t, w, h,
                  bg=INDIGO, fg=WHITE, font_size=Pt(11), bold=True, radius=True):
    """Coloured pill/badge label."""
    rect = add_rect(slide, l, t, w, h, fill_color=bg, border_color=None)
    add_text_box(slide, text, l, t, w, h,
                 font_size=font_size, bold=bold, color=fg,
                 align=PP_ALIGN.CENTER)
    return rect


def add_arrow(slide, l, t, w, h, horizontal=True):
    """Simple line arrow."""
    from pptx.util import Pt
    connector = slide.shapes.add_connector(
        1,  # MSO_CONNECTOR_TYPE.STRAIGHT
        Inches(l), Inches(t), Inches(l + w), Inches(t + h)
    )
    connector.line.color.rgb = INDIGO
    connector.line.width = Pt(2)
    return connector


# ── Build slides ─────────────────────────────────────────────────────────────

def slide_01_title(prs):
    """SLIDE 1: Title / Hero"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    set_bg(slide, DARK)

    # Gradient-ish top bar
    add_rect(slide, 0, 0, 13.33, 0.08, fill_color=INDIGO)

    # Logo mark placeholder
    add_rect(slide, 0.6, 1.1, 0.55, 0.55, fill_color=INDIGO, border_color=None)
    add_text_box(slide, "~", 0.6, 1.05, 0.55, 0.6,
                 font_size=Pt(22), bold=True, color=WHITE, align=PP_ALIGN.CENTER)

    # Title
    add_text_box(slide, "Signalwave", 1.3, 1.1, 5, 0.65,
                 font_size=Pt(38), bold=True, color=WHITE)
    add_text_box(slide, "Social Media Harassment Tracker", 1.3, 1.78, 7, 0.45,
                 font_size=Pt(18), color=RGBColor(0xC7, 0xC4, 0xE8))

    # Subtitle description
    desc = ("An end-to-end platform that monitors Facebook, Instagram and YouTube\n"
            "for harassing comments — detecting, hiding and reporting them automatically.")
    add_text_box(slide, desc, 1.3, 2.45, 10.5, 0.9,
                 font_size=Pt(13), color=RGBColor(0xA0, 0xA8, 0xC8), italic=True)

    # Platform badges
    for i, (label, color) in enumerate([
        ("🔵  Facebook", FB_BLUE),
        ("🟣  Instagram", IG_PURPLE),
        ("🔴  YouTube", YT_RED),
    ]):
        add_label_box(slide, label, 1.3 + i * 2.6, 3.6, 2.3, 0.45,
                      bg=color, fg=WHITE, font_size=Pt(12))

    # Tech stack row
    add_text_box(slide, "Python  ·  FastAPI  ·  PostgreSQL  ·  OpenAI GPT-4o  ·  JWT OAuth2  ·  APScheduler",
                 1.3, 4.35, 10.5, 0.4,
                 font_size=Pt(11), color=SOFT, italic=True, align=PP_ALIGN.CENTER)

    # Bottom bar
    add_rect(slide, 0, 7.27, 13.33, 0.23, fill_color=INDIGO)
    add_text_box(slide, "© 2026 Signalwave  |  End-to-End Architecture Overview", 0, 7.27, 13.33, 0.25,
                 font_size=Pt(9), color=WHITE, align=PP_ALIGN.CENTER)


def slide_02_architecture(prs):
    """SLIDE 2: High-Level System Architecture"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_bg(slide, LIGHT_BG)
    add_rect(slide, 0, 0, 13.33, 0.08, fill_color=INDIGO)

    add_text_box(slide, "System Architecture Overview", 0.4, 0.2, 12, 0.55,
                 font_size=Pt(22), bold=True, color=DARK)
    add_text_box(slide, "Three layers work together: Frontend → Backend API → Data & Platform APIs",
                 0.4, 0.78, 12, 0.35, font_size=Pt(12), color=SOFT)

    # Layer 1 — Frontend
    add_rect(slide, 0.3, 1.3, 3.6, 5.0, fill_color=INDIGO_LIGHT, border_color=INDIGO, border_width=Pt(1.5))
    add_text_box(slide, "① FRONTEND", 0.3, 1.3, 3.6, 0.42,
                 font_size=Pt(11), bold=True, color=INDIGO, align=PP_ALIGN.CENTER)
    for i, page in enumerate(["index.html (Login)", "onboarding.html", "dashboard.html",
                               "harassing-comments.html", "sentiment-analysis.html"]):
        add_rect(slide, 0.45, 1.9 + i * 0.77, 3.3, 0.6, fill_color=WHITE, border_color=BORDER)
        add_text_box(slide, page, 0.45, 1.9 + i * 0.77, 3.3, 0.62,
                     font_size=Pt(10.5), color=DARK, align=PP_ALIGN.CENTER)

    # Arrow →
    add_text_box(slide, "→", 4.15, 3.5, 0.6, 0.5, font_size=Pt(28), bold=True, color=INDIGO, align=PP_ALIGN.CENTER)

    # Layer 2 — FastAPI backend
    add_rect(slide, 4.9, 1.3, 3.8, 5.0, fill_color=RGBColor(0xEA, 0xF0, 0xFF), border_color=GOOGLE_BLUE, border_width=Pt(1.5))
    add_text_box(slide, "② FASTAPI BACKEND", 4.9, 1.3, 3.8, 0.42,
                 font_size=Pt(11), bold=True, color=GOOGLE_BLUE, align=PP_ALIGN.CENTER)
    for i, ep in enumerate(["POST /auth/register|login", "GET|POST /api/channels",
                             "GET /api/comments", "POST /auth/google|youtube",
                             "POST /api/tracker/run"]):
        add_rect(slide, 5.05, 1.9 + i * 0.77, 3.5, 0.6, fill_color=WHITE, border_color=BORDER)
        add_text_box(slide, ep, 5.05, 1.9 + i * 0.77, 3.5, 0.62,
                     font_size=Pt(10), color=DARK, align=PP_ALIGN.CENTER)

    # Arrow →
    add_text_box(slide, "→", 8.95, 3.5, 0.6, 0.5, font_size=Pt(28), bold=True, color=INDIGO, align=PP_ALIGN.CENTER)

    # Layer 3 — Data + Platforms
    add_rect(slide, 9.7, 1.3, 3.3, 5.0, fill_color=RGBColor(0xE9, 0xF8, 0xF0), border_color=POSITIVE, border_width=Pt(1.5))
    add_text_box(slide, "③ DATA & PLATFORMS", 9.7, 1.3, 3.3, 0.42,
                 font_size=Pt(11), bold=True, color=POSITIVE, align=PP_ALIGN.CENTER)
    for i, (label, color) in enumerate([
        ("PostgreSQL DB", DARK),
        ("Meta Graph API", FB_BLUE),
        ("YouTube Data API", YT_RED),
        ("OpenAI GPT-4o", NEUTRAL),
        ("APScheduler", INDIGO),
    ]):
        add_rect(slide, 9.85, 1.9 + i * 0.77, 3.0, 0.6, fill_color=WHITE, border_color=BORDER)
        add_text_box(slide, label, 9.85, 1.9 + i * 0.77, 3.0, 0.62,
                     font_size=Pt(10.5), color=color, bold=(color != DARK), align=PP_ALIGN.CENTER)

    add_rect(slide, 0, 7.27, 13.33, 0.23, fill_color=INDIGO)
    add_text_box(slide, "Signalwave  |  System Architecture", 0, 7.27, 13.33, 0.25,
                 font_size=Pt(9), color=WHITE, align=PP_ALIGN.CENTER)


def slide_03_user_journey(prs):
    """SLIDE 3: User Journey — Step by Step"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_bg(slide, LIGHT_BG)
    add_rect(slide, 0, 0, 13.33, 0.08, fill_color=INDIGO)

    add_text_box(slide, "User Journey — From Sign-Up to Tracking", 0.4, 0.2, 12, 0.55,
                 font_size=Pt(22), bold=True, color=DARK)

    steps = [
        ("1", "Visit\nindex.html", "User arrives at\nSignalwave login\npage", INDIGO),
        ("2", "Google\nOAuth Login", "Click 'Sign in\nwith Google'\n→ JWT issued", GOOGLE_BLUE),
        ("3", "Onboarding\nStep 1-2", "Select platform\n(YouTube) &\nConnect account", YT_RED),
        ("4", "Select\nChannel", "Choose which\nYT channel to\nmonitor", NEUTRAL),
        ("5", "Consent &\nConfirm", "Review permissions\nClick 'Confirm'\nPOST /api/channels", POSITIVE),
        ("6", "Dashboard\nLive!", "Dashboard auto-\ndetects channel\nShows tracking ON", INDIGO_DEEP),
    ]

    for i, (num, title, desc, color) in enumerate(steps):
        x = 0.3 + i * 2.17
        # Circle number
        add_rect(slide, x + 0.5, 1.2, 1.0, 0.9, fill_color=color, border_color=None)
        add_text_box(slide, num, x + 0.5, 1.15, 1.0, 0.9,
                     font_size=Pt(28), bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        # Card
        add_rect(slide, x + 0.1, 2.2, 1.85, 2.4, fill_color=WHITE, border_color=color, border_width=Pt(1.5))
        add_text_box(slide, title, x + 0.1, 2.25, 1.85, 0.55,
                     font_size=Pt(11), bold=True, color=color, align=PP_ALIGN.CENTER)
        add_text_box(slide, desc, x + 0.1, 2.85, 1.85, 1.7,
                     font_size=Pt(9.5), color=SOFT, align=PP_ALIGN.CENTER)
        # Arrow (not after last)
        if i < len(steps) - 1:
            add_text_box(slide, "→", x + 2.0, 1.4, 0.4, 0.6,
                         font_size=Pt(18), bold=True, color=INDIGO, align=PP_ALIGN.CENTER)

    # Bottom note
    add_text_box(slide, "All pages served at http://localhost:9000  •  Auth token stored in localStorage  •  JWT validated on every API call",
                 0.4, 5.0, 12.5, 0.4,
                 font_size=Pt(10), color=SOFT, italic=True, align=PP_ALIGN.CENTER)

    add_rect(slide, 0, 7.27, 13.33, 0.23, fill_color=INDIGO)
    add_text_box(slide, "Signalwave  |  User Journey", 0, 7.27, 13.33, 0.25,
                 font_size=Pt(9), color=WHITE, align=PP_ALIGN.CENTER)


def slide_04_auth_flow(prs):
    """SLIDE 4: Authentication & OAuth Flow"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_bg(slide, LIGHT_BG)
    add_rect(slide, 0, 0, 13.33, 0.08, fill_color=INDIGO)

    add_text_box(slide, "Authentication & OAuth Flow", 0.4, 0.2, 12, 0.55,
                 font_size=Pt(22), bold=True, color=DARK)

    # --- Sign-In Flow (left panel)
    add_rect(slide, 0.3, 0.9, 5.9, 5.5, fill_color=WHITE, border_color=GOOGLE_BLUE, border_width=Pt(1.5))
    add_text_box(slide, "SIGN-IN OAUTH  (Google Login)", 0.3, 0.9, 5.9, 0.42,
                 font_size=Pt(11), bold=True, color=GOOGLE_BLUE, align=PP_ALIGN.CENTER)

    sign_in_steps = [
        ("User clicks 'Sign in with Google'", DARK),
        ("→ /auth/google/start  (redirect to Google)", GOOGLE_BLUE),
        ("User grants permission on Google", DARK),
        ("→ /auth/google/callback  (backend receives code)", GOOGLE_BLUE),
        ("Backend exchanges code for profile info", DARK),
        ("→ User record created/updated in PostgreSQL", POSITIVE),
        ("→ JWT token generated (30-day expiry)", INDIGO),
        ("→ Redirect to dashboard.html?token=JWT", INDIGO),
        ("Token saved to localStorage", DARK),
    ]
    for i, (step, color) in enumerate(sign_in_steps):
        add_text_box(slide, step, 0.5, 1.42 + i * 0.5, 5.5, 0.45,
                     font_size=Pt(10), color=color)

    # --- YouTube Connection Flow (right panel)
    add_rect(slide, 7.0, 0.9, 5.9, 5.5, fill_color=WHITE, border_color=YT_RED, border_width=Pt(1.5))
    add_text_box(slide, "YOUTUBE CONNECT OAUTH", 7.0, 0.9, 5.9, 0.42,
                 font_size=Pt(11), bold=True, color=YT_RED, align=PP_ALIGN.CENTER)

    yt_steps = [
        ("Onboarding Step 2: click 'Continue with Google'", DARK),
        ("→ /auth/youtube/connect/start  (with JWT)", YT_RED),
        ("Redirected to Google (youtube.force-ssl scope)", DARK),
        ("→ /auth/youtube/connect/callback", YT_RED),
        ("Backend fetches channel list from YouTube API", DARK),
        ("→ OAuth tokens saved to PlatformAppCredential", POSITIVE),
        ("→ Redirect to onboarding.html?step=3&profiles=[…]", INDIGO),
        ("User selects channel → POST /api/channels", DARK),
        ("MonitoredChannel record saved in PostgreSQL", POSITIVE),
    ]
    for i, (step, color) in enumerate(yt_steps):
        add_text_box(slide, step, 7.2, 1.42 + i * 0.5, 5.5, 0.45,
                     font_size=Pt(10), color=color)

    # Divider label
    add_rect(slide, 6.3, 3.1, 0.75, 0.4, fill_color=INDIGO, border_color=None)
    add_text_box(slide, "VS", 6.3, 3.1, 0.75, 0.42,
                 font_size=Pt(11), bold=True, color=WHITE, align=PP_ALIGN.CENTER)

    add_rect(slide, 0, 7.27, 13.33, 0.23, fill_color=INDIGO)
    add_text_box(slide, "Signalwave  |  Authentication & OAuth Flow", 0, 7.27, 13.33, 0.25,
                 font_size=Pt(9), color=WHITE, align=PP_ALIGN.CENTER)


def slide_05_tracking_engine(prs):
    """SLIDE 5: Tracking & Detection Engine"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_bg(slide, LIGHT_BG)
    add_rect(slide, 0, 0, 13.33, 0.08, fill_color=INDIGO)

    add_text_box(slide, "Harassment Tracking & Detection Engine", 0.4, 0.2, 12, 0.55,
                 font_size=Pt(22), bold=True, color=DARK)
    add_text_box(slide, "APScheduler triggers tracker.py every 5 minutes  →  Comments are fetched, scored and stored",
                 0.4, 0.78, 12, 0.35, font_size=Pt(12), color=SOFT)

    # Pipeline boxes (horizontal flow)
    pipeline = [
        ("APScheduler\n(scheduler.py)", "Runs every\nPOLL_INTERVAL\n(default 5 min)", INDIGO),
        ("Fetch\nComments", "Facebook Pages\nInstagram Posts\nYouTube Videos", FB_BLUE),
        ("Detect\nHarassment", "Keyword match\n(EN/Tamil/Tanglish)\n+  GPT-4o AI Score", NEUTRAL),
        ("Store in\nPostgreSQL", "Comment table\nHarassScore\nPlatform + author", POSITIVE),
        ("Auto-\nModerate", "Hide/Delete\nhigh-scoring\ncomments", NEGATIVE),
        ("Flag\nUser", "FlaggedUser\ntable updated\ncomposite PK", DARK),
    ]

    for i, (title, desc, color) in enumerate(pipeline):
        x = 0.3 + i * 2.16
        add_rect(slide, x, 1.35, 1.9, 2.2, fill_color=color, border_color=None)
        add_text_box(slide, title, x, 1.35, 1.9, 0.7,
                     font_size=Pt(11), bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        add_rect(slide, x, 2.08, 1.9, 1.5, fill_color=WHITE, border_color=color, border_width=Pt(1))
        add_text_box(slide, desc, x, 2.1, 1.9, 1.5,
                     font_size=Pt(9), color=SOFT, align=PP_ALIGN.CENTER)
        if i < len(pipeline) - 1:
            add_text_box(slide, "→", x + 1.92, 2.0, 0.3, 0.5,
                         font_size=Pt(16), bold=True, color=INDIGO, align=PP_ALIGN.CENTER)

    # DB Schema section
    add_text_box(slide, "Key Database Tables", 0.4, 3.75, 5, 0.4,
                 font_size=Pt(13), bold=True, color=DARK)
    tables = [
        ("User", "id, email, google_id, youtube_id, is_active"),
        ("MonitoredChannel", "id, user_id, platform, name, access_token, is_active"),
        ("PlatformAppCredential", "user_id, platform, access_token, refresh_token, expiry"),
        ("Comment", "id, channel_id, post_id, author, text, harass_score, is_hidden"),
        ("FlaggedUser", "platform_user_id, platform, comment_count, first_seen"),
    ]
    for i, (table, cols) in enumerate(tables):
        add_rect(slide, 0.4, 4.2 + i * 0.56, 12.5, 0.52, fill_color=WHITE, border_color=BORDER)
        add_text_box(slide, table, 0.5, 4.22 + i * 0.56, 2.3, 0.5,
                     font_size=Pt(10), bold=True, color=INDIGO)
        add_text_box(slide, cols, 2.9, 4.22 + i * 0.56, 10, 0.5,
                     font_size=Pt(9.5), color=SOFT)

    add_rect(slide, 0, 7.27, 13.33, 0.23, fill_color=INDIGO)
    add_text_box(slide, "Signalwave  |  Tracking & Detection Engine", 0, 7.27, 13.33, 0.25,
                 font_size=Pt(9), color=WHITE, align=PP_ALIGN.CENTER)


def slide_06_dashboard(prs):
    """SLIDE 6: Dashboard & Real-Time Display"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_bg(slide, LIGHT_BG)
    add_rect(slide, 0, 0, 13.33, 0.08, fill_color=INDIGO)

    add_text_box(slide, "Dashboard — What the User Sees", 0.4, 0.2, 12, 0.55,
                 font_size=Pt(22), bold=True, color=DARK)

    # State A — No channels connected
    add_rect(slide, 0.3, 0.9, 5.9, 3.0, fill_color=WHITE, border_color=INDIGO, border_width=Pt(1.5))
    add_label_box(slide, "STATE A — No Channels", 0.3, 0.9, 5.9, 0.42,
                  bg=NEGATIVE, fg=WHITE, font_size=Pt(11))
    add_text_box(slide, "🔒  Harassing comment tracking is off\n\n"
                        "'Enable tracking' button shown\n"
                        "Clicking it redirects to onboarding.html\n\n"
                        "Dashboard auto-detects: channels.length === 0\n"
                        "→ setDemoState('new')",
                 0.5, 1.4, 5.5, 2.3, font_size=Pt(11), color=SOFT)

    # Arrow between states
    add_text_box(slide, "User completes\nonboarding\n→", 6.35, 1.8, 1.3, 1.0,
                 font_size=Pt(11), bold=True, color=INDIGO, align=PP_ALIGN.CENTER)

    # State B — Channels connected
    add_rect(slide, 7.7, 0.9, 5.3, 3.0, fill_color=WHITE, border_color=POSITIVE, border_width=Pt(1.5))
    add_label_box(slide, "STATE B — Tracking Active", 7.7, 0.9, 5.3, 0.42,
                  bg=POSITIVE, fg=WHITE, font_size=Pt(11))
    add_text_box(slide, "✅  Harassment stats displayed:\n"
                        "   Flagged  |  Deleted  |  Hidden  |  Reported\n\n"
                        "📊  Comments over 14 days (bar chart)\n"
                        "📈  Likes vs Comments (line chart)\n"
                        "😊  Sentiment snapshot (score + seg bar)\n\n"
                        "Dashboard auto-detects: channels.length > 0\n"
                        "→ setDemoState('full')",
                 7.9, 1.4, 4.9, 2.3, font_size=Pt(10), color=SOFT)

    # How dashboard detects state
    add_rect(slide, 0.3, 4.1, 12.7, 1.6, fill_color=INDIGO_LIGHT, border_color=INDIGO)
    add_text_box(slide, "How Dashboard Detects State (API call on page load)", 0.5, 4.15, 12.3, 0.42,
                 font_size=Pt(12), bold=True, color=INDIGO)
    add_text_box(
        slide,
        "fetch('/api/channels', { headers: { Authorization: 'Bearer ' + localStorage.sw_token } })\n"
        "  .then(channels => channels.length > 0 ? setDemoState('full') : setDemoState('new'))",
        0.5, 4.6, 12.3, 0.9, font_size=Pt(10.5), color=DARK
    )

    # API endpoints used
    add_text_box(slide, "Dashboard API Endpoints", 0.4, 5.85, 4, 0.4,
                 font_size=Pt(13), bold=True, color=DARK)
    endpoints = [
        ("GET /api/channels", "List this user's monitored channels (auth required)", INDIGO),
        ("GET /api/comments?harassing=true", "Fetch flagged harassing comments", NEGATIVE),
        ("GET /api/flagged-users", "List all flagged user profiles", NEUTRAL),
        ("POST /api/tracker/run", "Manually trigger a tracker run", POSITIVE),
    ]
    for i, (ep, desc, color) in enumerate(endpoints):
        add_rect(slide, 0.4, 6.3 + i * 0.24, 12.5, 0.23, fill_color=WHITE, border_color=BORDER)
        add_text_box(slide, ep, 0.5, 6.3 + i * 0.24, 3.0, 0.23,
                     font_size=Pt(9), bold=True, color=color)
        add_text_box(slide, desc, 3.6, 6.3 + i * 0.24, 9.0, 0.23,
                     font_size=Pt(9), color=SOFT)

    add_rect(slide, 0, 7.27, 13.33, 0.23, fill_color=INDIGO)
    add_text_box(slide, "Signalwave  |  Dashboard & Display Logic", 0, 7.27, 13.33, 0.25,
                 font_size=Pt(9), color=WHITE, align=PP_ALIGN.CENTER)


def slide_07_detection(prs):
    """SLIDE 7: AI Detection Deep Dive"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_bg(slide, LIGHT_BG)
    add_rect(slide, 0, 0, 13.33, 0.08, fill_color=INDIGO)

    add_text_box(slide, "Comment Analysis — Detection Pipeline", 0.4, 0.2, 12, 0.55,
                 font_size=Pt(22), bold=True, color=DARK)

    # Left: Input
    add_rect(slide, 0.3, 0.95, 3.2, 5.5, fill_color=WHITE, border_color=BORDER)
    add_label_box(slide, "INPUT", 0.3, 0.95, 3.2, 0.4, bg=DARK, fg=WHITE, font_size=Pt(11))
    inputs = [
        ("Raw Comment Text", DARK),
        ("Author Platform ID", SOFT),
        ("Platform (FB/IG/YT)", SOFT),
        ("Post ID", SOFT),
        ("Timestamp", SOFT),
        ("", SOFT),
        ("Languages Supported:", DARK),
        ("🇬🇧  English", POSITIVE),
        ("🇮🇳  Tamil", POSITIVE),
        ("🌐  Tanglish", POSITIVE),
    ]
    for i, (label, color) in enumerate(inputs):
        add_text_box(slide, label, 0.5, 1.45 + i * 0.47, 2.8, 0.44,
                     font_size=Pt(10.5), color=color)

    # Middle: Processing
    add_rect(slide, 3.8, 0.95, 5.5, 5.5, fill_color=INDIGO_LIGHT, border_color=INDIGO)
    add_label_box(slide, "PROCESSING  (detector.py)", 3.8, 0.95, 5.5, 0.4,
                  bg=INDIGO, fg=WHITE, font_size=Pt(11))

    stages = [
        ("Step 1: Language Detection", "langdetect → identify EN / ta / mix", INDIGO),
        ("Step 2: Keyword Matching", "600+ harassment keywords\nacross all 3 languages", NEUTRAL),
        ("Step 3: AI Scoring  (optional)", "OpenAI GPT-4o or Gemini\nReturns harassment_score 0.0–1.0", GOOGLE_BLUE),
        ("Step 4: Threshold Check", "score > 0.6  →  flag as harassing\nscore > 0.85 →  auto-hide/delete", NEGATIVE),
    ]
    for i, (title, desc, color) in enumerate(stages):
        add_rect(slide, 3.95, 1.5 + i * 1.2, 5.1, 1.05, fill_color=WHITE, border_color=color)
        add_text_box(slide, title, 4.05, 1.52 + i * 1.2, 4.9, 0.38,
                     font_size=Pt(10), bold=True, color=color)
        add_text_box(slide, desc, 4.05, 1.9 + i * 1.2, 4.9, 0.55,
                     font_size=Pt(9.5), color=SOFT)

    # Right: Output
    add_rect(slide, 9.55, 0.95, 3.45, 5.5, fill_color=WHITE, border_color=BORDER)
    add_label_box(slide, "OUTPUT", 9.55, 0.95, 3.45, 0.4, bg=POSITIVE, fg=WHITE, font_size=Pt(11))
    outputs = [
        ("✅ Stored in Comment table", DARK),
        ("", SOFT),
        ("harass_score: 0.0 – 1.0", SOFT),
        ("is_harassing: True/False", SOFT),
        ("is_hidden: True/False", SOFT),
        ("", SOFT),
        ("If is_harassing = True:", NEGATIVE),
        ("→ FlaggedUser updated", NEGATIVE),
        ("→ CommentAction logged", NEGATIVE),
        ("→ Platform hide/delete", NEGATIVE),
        ("→ Dashboard counter ++", NEGATIVE),
    ]
    for i, (label, color) in enumerate(outputs):
        add_text_box(slide, label, 9.7, 1.45 + i * 0.46, 3.1, 0.44,
                     font_size=Pt(10), color=color)

    # Arrows
    add_text_box(slide, "→", 3.3, 3.5, 0.55, 0.5,
                 font_size=Pt(22), bold=True, color=INDIGO, align=PP_ALIGN.CENTER)
    add_text_box(slide, "→", 9.2, 3.5, 0.42, 0.5,
                 font_size=Pt(22), bold=True, color=POSITIVE, align=PP_ALIGN.CENTER)

    add_rect(slide, 0, 7.27, 13.33, 0.23, fill_color=INDIGO)
    add_text_box(slide, "Signalwave  |  AI Detection Pipeline", 0, 7.27, 13.33, 0.25,
                 font_size=Pt(9), color=WHITE, align=PP_ALIGN.CENTER)


def slide_08_tech_stack(prs):
    """SLIDE 8: Technology Stack Summary"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_bg(slide, DARK)
    add_rect(slide, 0, 0, 13.33, 0.08, fill_color=INDIGO)

    add_text_box(slide, "Technology Stack", 0.4, 0.2, 12, 0.55,
                 font_size=Pt(22), bold=True, color=WHITE)
    add_text_box(slide, "Every component that powers Signalwave end-to-end",
                 0.4, 0.78, 12, 0.35, font_size=Pt(12), color=RGBColor(0xA0, 0xA8, 0xC8), italic=True)

    categories = [
        ("BACKEND", [
            ("Python 3.11+", "Core language"),
            ("FastAPI + Uvicorn", "REST API & async server"),
            ("SQLAlchemy 2.x", "ORM for PostgreSQL"),
            ("psycopg2", "PostgreSQL driver"),
            ("APScheduler", "Polling scheduler"),
            ("python-jose", "JWT token generation"),
            ("passlib + bcrypt", "Password hashing"),
            ("loguru", "Structured logging"),
        ], INDIGO),
        ("FRONTEND", [
            ("HTML5 + CSS3", "Static pages"),
            ("Vanilla JS", "No framework needed"),
            ("localStorage", "JWT token storage"),
            ("Fetch API", "Backend communication"),
            ("Google Fonts", "Plus Jakarta Sans / Inter"),
            ("SVG Icons", "Inline icon system"),
        ], GOOGLE_BLUE),
        ("PLATFORM APIs", [
            ("Meta Graph API v19", "Facebook & Instagram"),
            ("YouTube Data API v3", "Comment moderation"),
            ("Google OAuth2", "Login + YouTube connect"),
            ("OpenAI GPT-4o", "AI harassment scoring"),
            ("Gemini (optional)", "Alternative AI provider"),
            ("langdetect", "Language identification"),
        ], YT_RED),
        ("INFRA / DATA", [
            ("PostgreSQL", "Primary database"),
            ("harassment_tracker schema", "Isolated DB namespace"),
            ("GitHub Pages", "Frontend hosting"),
            (".env config", "Secrets management"),
            ("pydantic-settings", "Config validation"),
            ("python-dotenv", "Env loading"),
        ], POSITIVE),
    ]

    for col, (cat_name, items, color) in enumerate(categories):
        x = 0.3 + col * 3.25
        add_rect(slide, x, 1.2, 3.05, 0.42, fill_color=color, border_color=None)
        add_text_box(slide, cat_name, x, 1.2, 3.05, 0.42,
                     font_size=Pt(11), bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        for i, (name, desc) in enumerate(items):
            add_rect(slide, x, 1.7 + i * 0.68, 3.05, 0.62,
                     fill_color=RGBColor(0x22, 0x27, 0x40), border_color=RGBColor(0x38, 0x3E, 0x58))
            add_text_box(slide, name, x + 0.1, 1.72 + i * 0.68, 2.85, 0.3,
                         font_size=Pt(10.5), bold=True, color=color)
            add_text_box(slide, desc, x + 0.1, 2.02 + i * 0.68, 2.85, 0.28,
                         font_size=Pt(9), color=RGBColor(0x80, 0x88, 0xA8))

    add_rect(slide, 0, 7.27, 13.33, 0.23, fill_color=INDIGO)
    add_text_box(slide, "Signalwave  |  Technology Stack", 0, 7.27, 13.33, 0.25,
                 font_size=Pt(9), color=WHITE, align=PP_ALIGN.CENTER)


def slide_09_summary(prs):
    """SLIDE 9: Summary / What We Built"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    set_bg(slide, DARK)
    add_rect(slide, 0, 0, 13.33, 0.08, fill_color=INDIGO)

    add_text_box(slide, "What We Built", 0.4, 0.2, 12, 0.55,
                 font_size=Pt(22), bold=True, color=WHITE)

    achievements = [
        ("🔐", "JWT Auth System", "Email/password + Google OAuth login with 30-day tokens"),
        ("🔗", "OAuth Account Connection", "YouTube & Meta OAuth flows to link social accounts to monitor"),
        ("📋", "Onboarding Wizard", "5-step wizard: platform → connect → select → consent → done"),
        ("🗄️", "PostgreSQL Schema", "8 tables: Users, Channels, Posts, Comments, FlaggedUsers, Actions"),
        ("🤖", "AI Detection Engine", "GPT-4o + keywords for EN/Tamil/Tanglish harassment detection"),
        ("⏰", "Auto Scheduler", "APScheduler polls platforms every 5 minutes automatically"),
        ("🚫", "Auto-Moderation", "High-scoring comments hidden/deleted via platform APIs"),
        ("📊", "Live Dashboard", "State-aware UI: shows tracking stats or onboarding CTA from DB"),
        ("🌐", "Multi-Platform", "One codebase handles Facebook Pages, Instagram, YouTube channels"),
    ]

    for i, (icon, title, desc) in enumerate(achievements):
        row = i % 3
        col = i // 3
        x = 0.4 + col * 4.3
        y = 1.2 + row * 1.9
        add_rect(slide, x, y, 3.9, 1.65,
                 fill_color=RGBColor(0x22, 0x27, 0x40), border_color=INDIGO, border_width=Pt(1))
        add_text_box(slide, icon + "  " + title, x + 0.15, y + 0.1, 3.6, 0.45,
                     font_size=Pt(12), bold=True, color=WHITE)
        add_text_box(slide, desc, x + 0.15, y + 0.55, 3.6, 0.95,
                     font_size=Pt(9.5), color=RGBColor(0xA0, 0xA8, 0xC8))

    # Bottom CTA
    add_rect(slide, 0.4, 6.85, 12.5, 0.32, fill_color=INDIGO, border_color=None)
    add_text_box(slide, "Next Steps:  Wire dashboard data endpoints  →  Start scheduler  →  Test end-to-end tracking  →  Deploy",
                 0.4, 6.85, 12.5, 0.34, font_size=Pt(10.5), bold=True, color=WHITE, align=PP_ALIGN.CENTER)

    add_rect(slide, 0, 7.27, 13.33, 0.23, fill_color=INDIGO)
    add_text_box(slide, "Signalwave  |  Project Summary", 0, 7.27, 13.33, 0.25,
                 font_size=Pt(9), color=WHITE, align=PP_ALIGN.CENTER)


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    prs = Presentation()
    prs.slide_width  = Inches(13.33)
    prs.slide_height = Inches(7.5)

    print("Generating slides...")
    slide_01_title(prs)
    print("  ✓ Slide 1: Title")
    slide_02_architecture(prs)
    print("  ✓ Slide 2: Architecture Overview")
    slide_03_user_journey(prs)
    print("  ✓ Slide 3: User Journey")
    slide_04_auth_flow(prs)
    print("  ✓ Slide 4: Auth & OAuth Flow")
    slide_05_tracking_engine(prs)
    print("  ✓ Slide 5: Tracking Engine")
    slide_06_dashboard(prs)
    print("  ✓ Slide 6: Dashboard")
    slide_07_detection(prs)
    print("  ✓ Slide 7: AI Detection Pipeline")
    slide_08_tech_stack(prs)
    print("  ✓ Slide 8: Technology Stack")
    slide_09_summary(prs)
    print("  ✓ Slide 9: Project Summary")

    out_path = os.path.join(os.path.dirname(__file__), "Signalwave_Presentation.pptx")
    prs.save(out_path)
    print(f"\n✅  Saved to: {out_path}")
    return out_path


if __name__ == "__main__":
    main()
