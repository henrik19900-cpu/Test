"""Dashboard: Norsk Tipping's odds against margin-free reference odds, one card per match.

Start with `streamlit run app.py`, or deploy it on Streamlit Community Cloud (see the README). When
Norsk Tipping's odds are older than interval_minutes (no `oddscompare run` beside it, as on Streamlit
Cloud), the page fetches them itself. Reference odds are fetched only with the button.
"""

from __future__ import annotations

import html
import os
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
import yaml

try:
    import oddscompare  # noqa: F401  (installed with pip install -e .)
except ImportError:  # Streamlit Cloud installs requirements.txt only: use the package from src/
    sys.path.insert(0, str(Path(__file__).with_name("src")))

from oddscompare import bets, calc, config, dashboard, db, fetch
from oddscompare.matching import Aliases
from oddscompare.sources import OUTCOMES

PAGE_SIZE = 24
COLOURS = {"H": "#2563eb", "U": "#7c3aed", "B": "#d97706"}
SOURCE_NAMES = {
    "norsk_tipping": "Norsk Tipping",
    "the_odds_api": "The Odds API",
    "odds_api_io": "Odds-API.io",
}

CSS = """
<style>
.oc-teams { font-weight: 700; font-size: 1.05rem; line-height: 1.3; }
.oc-meta { opacity: 0.75; font-size: 0.85rem; margin-bottom: 0.5rem; }
.oc-row { display: flex; gap: 0.5rem; }
.oc-cell { flex: 1 1 0; min-width: 0; text-align: center; border: 1px solid rgba(128,128,128,0.3);
           border-radius: 0.5rem; padding: 0.4rem 0.2rem; }
.oc-label { font-size: 0.8rem; opacity: 0.75; }
.oc-odds { font-size: 1.6rem; font-weight: 700; line-height: 1.2; }
.oc-fair { font-size: 0.85rem; opacity: 0.8; }
.oc-ev { display: inline-block; margin-top: 0.25rem; padding: 0.05rem 0.45rem; border-radius: 999px;
         font-size: 0.85rem; font-weight: 600; color: #fff; }
.oc-ev.pos { background: #1e7b34; }
.oc-ev.neutral { background: #5f6672; }
.oc-ev.neg { background: #b42318; }
.oc-ev.none { background: transparent; color: inherit; opacity: 0.6; }
.oc-foot { font-size: 0.8rem; opacity: 0.8; margin-top: 0.5rem; }
.oc-stale { color: #b42318; font-weight: 600; }
.oc-best { font-size: 0.85rem; margin-top: 0.4rem; }
.oc-best b { font-variant-numeric: tabular-nums; }
.oc-nt-best { color: #1e7b34; font-weight: 600; }
table.oc-books { width: 100%; border-collapse: collapse; font-size: 0.88rem; font-variant-numeric: tabular-nums; }
table.oc-books th, table.oc-books td { padding: 0.2rem 0.4rem; text-align: right; border-bottom: 1px solid rgba(128,128,128,0.25); }
table.oc-books th:first-child, table.oc-books td:first-child { text-align: left; }
table.oc-books td.top { font-weight: 700; }
table.oc-books tr.nt td { background: rgba(128,128,128,0.10); }
/* One card per row on narrow screens (the cards are laid out in Streamlit columns). */
@media (max-width: 700px) {
  div[data-testid="stHorizontalBlock"] { flex-direction: column !important; }
  div[data-testid="stHorizontalBlock"] > div { width: 100% !important; flex: 1 1 100% !important; min-width: 100% !important; }
}
</style>
"""


def percent(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "–"
    text = f"{value * 100:+.1f} %" if signed else f"{value * 100:.1f} %"
    return text.replace(".", ",").replace("-", "−")


def odds_text(value: float | None) -> str:
    return "–" if value is None else f"{value:.2f}".replace(".", ",")


def local(moment: datetime, fmt: str = "%a %d.%m %H:%M") -> str:
    days = {
        "Mon": "man.",
        "Tue": "tir.",
        "Wed": "ons.",
        "Thu": "tor.",
        "Fri": "fre.",
        "Sat": "lør.",
        "Sun": "søn.",
    }
    text = moment.astimezone(dashboard.OSLO).strftime(fmt)
    for english, norwegian in days.items():
        text = text.replace(english, norwegian)
    return text


def card_html(
    card: dashboard.Card,
    now: datetime,
    stale_after: timedelta,
    reference_name: str,
) -> str:
    e = html.escape
    cells = []
    for i, label in enumerate(("H", "U", "B")):
        ev = card.ev[i] if card.ev else None
        fair = card.fair_odds[i] if card.fair_odds else None
        cells.append(
            f'<div class="oc-cell"><div class="oc-label">{label}</div>'
            f'<div class="oc-odds">{odds_text(card.nt_odds[i])}</div>'
            f'<div class="oc-fair">fair {odds_text(fair)}</div>'
            f'<div class="oc-ev {dashboard.ev_class(ev)}">EV {percent(ev, signed=True)}</div></div>'
        )
    times = f"NT {local(card.nt_fetched, '%H:%M')}"
    if card.ref_fetched:
        times += f" · {e(reference_name)} {local(card.ref_fetched, '%H:%M')}"
    # Only Norsk Tipping's age is warned about: the reference is as old as the last time it was asked for.
    warning = (
        '<div class="oc-stale">Gamle odds fra Norsk Tipping: sjekk at hentingen kjører</div>'
        if card.stale(now, stale_after)
        else ""
    )
    if card.nt_moved:
        warning += (
            '<div class="oc-stale">Norsk Tipping har endret oddsen etter siste referansehenting. '
            "Fair odds og EV kan være utdaterte: hent referanseodds før du spiller.</div>"
        )
    if card.doubtful:
        warning += (
            f'<div class="oc-stale">{e(reference_name)}-marginen er uvanlig høy ({percent(card.ref_margin)}), '
            "så fair odds og EV er usikre.</div>"
        )
    if card.fair_from == "konkurrenter":
        missing = (
            f'<div class="oc-foot">Fair odds fra snittet av {len(card.competitors)} konkurrenter: '
            f"{e(reference_name)} har ikke odds på kampen ennå.</div>"
        )
    elif not card.ref_odds:
        missing = '<div class="oc-foot">Ingen referanseodds for denne kampen ennå.</div>'
    else:
        missing = ""
    return (
        f'<div class="oc-teams">{e(card.home)} – {e(card.away)}</div>'
        f'<div class="oc-meta">{e(card.league)} · {local(card.kickoff_utc)}</div>'
        f'<div class="oc-row">{"".join(cells)}</div>'
        f"{best_line(card)}"
        f'<div class="oc-foot">NT-margin {percent(card.nt_margin)} · referansemargin {percent(card.ref_margin)}'
        f"<br>Sist hentet: {times}</div>{warning}{missing}"
    )


def best_line(card: dashboard.Card) -> str:
    """«Beste odds: H 2,15 Betsson · U 3,60 Norsk Tipping · …», when competitors' odds are there."""
    if not card.competitors:
        return ""
    parts = []
    for label, (price, names) in zip(("H", "U", "B"), card.best_prices(), strict=True):
        css = ' class="oc-nt-best"' if "Norsk Tipping" in names else ""
        parts.append(f"<span{css}>{label} <b>{odds_text(price)}</b> {html.escape(', '.join(names))}</span>")
    return f'<div class="oc-best">Beste odds: {" · ".join(parts)}</div>'


def books_table(card: dashboard.Card) -> str:
    """Norsk Tipping and every competitor side by side; the best price per outcome in bold."""
    best = [price for price, _ in card.best_prices()]
    rows = []
    for source, odds in {dashboard.NT: card.nt_odds, **card.competitors}.items():
        cells = "".join(
            f'<td class="{"top" if o == best[i] else ""}">{odds_text(o)}</td>' for i, o in enumerate(odds)
        )
        css = ' class="nt"' if source == dashboard.NT else ""
        rows.append(
            f"<tr{css}><td>{html.escape(dashboard.bookmaker_name(source))}</td>{cells}"
            f"<td>{percent(calc.margin(odds))}</td></tr>"
        )
    head = "<tr><th>Bookmaker</th><th>H</th><th>U</th><th>B</th><th>Margin</th></tr>"
    return f'<table class="oc-books">{head}{"".join(rows)}</table>'


def history_chart(frame) -> go.Figure:
    figure = go.Figure()
    for (series, label), part in frame.groupby(["serie", "utfall"], sort=False):
        figure.add_trace(
            go.Scatter(
                x=part["tid"],
                y=part["odds"],
                mode="lines+markers",
                name=f"{label} {'NT' if series == 'Norsk Tipping' else 'fair'}",
                line={"color": COLOURS[label], "dash": "solid" if series == "Norsk Tipping" else "dot"},
                marker={"size": 4},
            )
        )
    figure.update_layout(
        height=260,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        legend={"orientation": "h", "y": -0.25},
        yaxis_title="Odds",
        xaxis_tickformat="%H:%M<br>%d.%m",
        hovermode="x unified",
    )
    return figure


RESULT_NAMES = {None: "Åpen", "won": "Vunnet", "lost": "Tapt", "void": "Annullert"}


def kroner(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "–"
    text = f"{value:+,.0f}" if signed else f"{value:,.0f}"
    return text.replace(",", " ").replace("-", "−") + " kr"


def bet_form(conn, card: dashboard.Card, reference_name: str) -> None:
    """Log a bet on this match, with the fair odds and EV as they are now."""
    best = max(range(3), key=lambda i: card.ev[i]) if card.ev else 0
    with st.form(f"bet-{card.event_id}", clear_on_submit=True, border=False):
        outcome = st.radio(
            "Utfall",
            OUTCOMES,
            index=best,
            horizontal=True,
            format_func=lambda o: f"{dashboard.LABELS[o]} ({odds_text(card.nt_odds[OUTCOMES.index(o)])})",
            key=f"bet-outcome-{card.event_id}",
        )
        odds = st.number_input(
            "Odds du fikk",
            min_value=1.01,
            value=None,
            step=0.05,
            format="%.2f",
            placeholder="Norsk Tippings odds for utfallet",
            key=f"bet-odds-{card.event_id}",
        )
        stake = st.number_input(
            "Innsats (kr)", min_value=1.0, value=100.0, step=50.0, key=f"bet-stake-{card.event_id}"
        )
        note = st.text_input("Notat (valgfritt)", key=f"bet-note-{card.event_id}")
        if st.form_submit_button("Lagre spill"):
            i = OUTCOMES.index(outcome)
            bets.add(
                conn,
                nt_event_id=bets.nt_event_id(conn, card.event_id),
                league=card.league,
                home=card.home,
                away=card.away,
                kickoff_utc=card.kickoff_utc,
                outcome=outcome,
                odds=odds or card.nt_odds[i],
                stake=stake,
                fair_at_bet=card.fair_odds[i] if card.fair_odds else None,
                fair_source_at_bet=("konkurrenter" if card.fair_from else reference_name)
                if card.fair_odds
                else None,
                note=note,
            )
            st.toast("Spillet er lagret under «Mine spill».")


def verdict(estimate: bets.Estimate, what: str) -> str:
    """How sure an average is, in words."""
    if estimate.n == 0:
        return ""
    if not estimate.enough:
        return (
            f"{what}: {percent(estimate.mean, signed=True)} i snitt etter {estimate.n} spill. "
            f"Det trengs minst {bets.MIN_FOR_STATS} før usikkerheten kan regnes ut."
        )
    text = (
        f"{what}: {percent(estimate.mean, signed=True)} i snitt etter {estimate.n} spill, "
        f"95 % sikkert mellom {percent(estimate.low, signed=True)} og {percent(estimate.high, signed=True)}. "
    )
    p = f"{estimate.p:.3f}".replace(".", ",")
    if estimate.p < 0.05:
        return text + f"Det er signifikant: et så godt snitt er usannsynlig uten en reell fordel (p = {p})."
    text += f"Ikke signifikant ennå (p = {p})."
    if estimate.bets_needed:
        text += f" Holder snittet seg, trengs rundt {estimate.bets_needed} spill i alt."
    return text


def bets_tab(conn) -> None:
    rows = bets.all_bets(conn)
    if not rows:
        st.info(
            "Ingen spill ennå. Registrer et spill under «Registrer spill» på et kort, eller last opp en spillogg."
        )
    else:
        s = bets.summarize(rows)
        top = st.columns(4)
        top[0].metric("Spill", s.bets, help=f"{s.open} uten resultat ennå")
        settled = s.bets - s.open
        top[1].metric(
            "Resultat",
            kroner(s.profit, signed=True) if settled else "–",
            help=f"ROI {percent(s.roi, signed=True)} av {kroner(s.staked)} avgjort",
        )
        top[2].metric(
            "Snitt-CLV",
            percent(s.clv.mean, signed=True) if s.clv.n else "–",
            help=f"{s.clv.n} spill med sluttodds",
        )
        top[3].metric(
            "Forventet etter EV",
            kroner(s.expected_profit, signed=True) if settled else "–",
            help="Det EV-en da du spilte tilsier, for avgjorte spill",
        )
        lines = [verdict(s.clv, "CLV"), verdict(s.returns, "Avkastning per spilt krone")]
        if not s.clv.n:
            lines.insert(
                0, "CLV vises når referanseodds er hentet etter at du har spilt, helst like før avspark."
            )
        st.markdown("  \n".join(line for line in lines if line))
        table = [
            {
                "id": b["id"],
                "Avspark": local(db.parse_iso(b["kickoff_utc"])),
                "Kamp": f"{b['home']} – {b['away']}",
                "Utfall": dashboard.LABELS[b["outcome"]],
                "Odds": b["odds"],
                "Innsats": b["stake"],
                "EV ved spill": percent(bets.ev_at_bet(b), signed=True),
                "Fair sluttodds": odds_text(b["closing_fair"]) if bets.clv(b) is not None else "venter",
                "CLV": percent(bets.clv(b), signed=True),
                "Resultat": RESULT_NAMES[b["result"]],
                "Gevinst": kroner(bets.profit(b), signed=True) if b["result"] else "",
                "Slett": False,
            }
            for b in rows
        ]
        edited = st.data_editor(
            table,
            hide_index=True,
            width="stretch",
            disabled=["Avspark", "Kamp", "Utfall", "EV ved spill", "Fair sluttodds", "CLV", "Gevinst"],
            column_order=[k for k in table[0] if k != "id"],
            column_config={
                "Resultat": st.column_config.SelectboxColumn(
                    options=list(RESULT_NAMES.values()), required=True
                ),
                "Odds": st.column_config.NumberColumn(min_value=1.01, format="%.2f"),
                "Innsats": st.column_config.NumberColumn(min_value=1.0, format="%.0f kr"),
            },
            key="bets-table",
        )
        if st.button("Lagre endringer"):
            by_name = {v: k for k, v in RESULT_NAMES.items()}
            for old, new in zip(table, edited, strict=True):
                if new["Slett"]:
                    bets.delete(conn, [old["id"]])
                    continue
                if new["Resultat"] != old["Resultat"]:
                    bets.set_result(conn, old["id"], by_name.get(new["Resultat"]))
                if new["Odds"] != old["Odds"] or new["Innsats"] != old["Innsats"]:
                    note = next(b["note"] for b in rows if b["id"] == old["id"])
                    bets.update(conn, old["id"], odds=new["Odds"], stake=new["Innsats"], note=note)
            st.rerun()
        st.download_button(
            "Last ned spillogg (CSV)", bets.to_csv(rows), file_name="spillogg.csv", mime="text/csv"
        )
    st.caption(
        "På Streamlit Cloud forsvinner databasen når appen startes på nytt. Last ned spilloggen jevnlig, "
        "og last den opp igjen her om den er borte."
    )
    upload = st.file_uploader("Last opp spillogg (CSV)", type="csv", key="bets-upload")
    if upload is not None and st.session_state.get("bets-uploaded") != upload.file_id:
        try:
            count = bets.from_csv(conn, upload.getvalue().decode("utf-8"))
        except (ValueError, KeyError, UnicodeDecodeError) as e:
            st.error(f"Kunne ikke lese filen: {e}")
        else:
            st.session_state["bets-uploaded"] = upload.file_id
            st.success(f"Leste {count} spill fra filen.")
            st.rerun()


def reference_panel(cfg: config.Config, conn, reference: str) -> None:
    """Reference odds cost credits, so they are fetched only when this button is pressed."""
    st.divider()
    st.subheader("Referanseodds")
    last = dashboard.last_success(conn, reference)
    lines = [f"Sist hentet: {local(last) if last else 'aldri'}."]
    request_cfg = cfg
    if reference == "the_odds_api":
        configured = cfg.reference.the_odds_api.leagues
        leagues = st.multiselect(
            "Ligaer",
            configured,
            default=configured,
            format_func=lambda key: dashboard.LEAGUE_NAMES.get(key, key),
            help="Hver liga koster 1 kreditt per henting, bare når Norsk Tipping har kamper i den.",
        )
        request_cfg = cfg.model_copy(
            update={
                "reference": cfg.reference.model_copy(
                    update={
                        "the_odds_api": cfg.reference.the_odds_api.model_copy(update={"leagues": leagues})
                    }
                )
            }
        )
        credits = dashboard.credits_left(cfg.cache_dir, reference)
        if credits is not None:
            lines.append(f"Kreditter igjen denne måneden: {credits}.")
        lines.append(f"Hentingen koster opptil {len(leagues)} kreditter, én per valgt liga med kamper.")
    st.caption(" ".join(lines))
    if st.button(
        "Hent referanseodds",
        type="primary",
        width="stretch",
        disabled=request_cfg is not cfg and not leagues,
    ):
        with st.spinner("Henter referanseodds …"):
            report = fetch.run_once(request_cfg, include_reference=True)
        st.session_state["reference_result"] = (
            all(s.status == "ok" for s in report.sources),
            fetch.summary(report),
        )
        st.rerun()
    if "reference_result" in st.session_state:
        ok, text = st.session_state["reference_result"]
        (st.success if ok else st.error)(text.replace("\n", "  \n"))


def secrets_to_environment() -> None:
    """API keys from Streamlit's secrets (Streamlit Cloud), for the code that reads them from the environment."""
    try:
        for name in ("THE_ODDS_API_KEY", "ODDS_API_IO_KEY"):
            if not os.environ.get(name) and st.secrets.get(name):
                os.environ[name] = str(st.secrets[name])
    except FileNotFoundError:  # no secrets.toml: .env is used instead
        pass
    except Exception:  # noqa: BLE001  (older Streamlit versions raise their own error for missing secrets)
        pass


@st.cache_resource
def fetch_lock() -> threading.Lock:
    """One Norsk Tipping fetch at a time, however many people have the page open."""
    return threading.Lock()


def refresh_norsk_tipping(cfg: config.Config, conn) -> None:
    """Fetch Norsk Tipping when its odds are older than interval_minutes (no fetcher running beside the page)."""
    last = dashboard.last_success(conn, dashboard.NT)
    if last and datetime.now(UTC) - last < timedelta(minutes=cfg.interval_minutes):
        return
    lock = fetch_lock()
    if not lock.acquire(blocking=False):
        return
    try:
        with st.spinner("Henter Norsk Tippings odds …"):
            fetch.run_once(cfg)
    finally:
        lock.release()


# Streamlit has no setting for the page head, so the tags «Add to Home Screen» reads are added from a
# script. The files are in static/, served at app/static/ (enableStaticServing in .streamlit/config.toml).
HOME_SCREEN = """<script>
const doc = window.parent.document;
const tags = [
  ["link", {rel: "apple-touch-icon", href: "app/static/apple-touch-icon.png"}],
  ["link", {rel: "manifest", href: "app/static/manifest.webmanifest"}],
  ["meta", {name: "apple-mobile-web-app-title", content: "Odds"}],
  ["meta", {name: "apple-mobile-web-app-capable", content: "yes"}],
  ["meta", {name: "mobile-web-app-capable", content: "yes"}],
  ["meta", {name: "theme-color", content: "#1e7b34"}],
];
for (const [tag, attrs] of tags) {
  const [key, value] = Object.entries(attrs)[0];
  if (doc.head.querySelector(`${tag}[${key}="${value}"]`)) continue;
  const el = doc.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  doc.head.appendChild(el);
}
</script>"""


def home_screen_tags() -> None:
    """Icon, name and full-screen start for a shortcut on the phone's home screen."""
    try:
        components.html(HOME_SCREEN, height=0)
    except Exception:  # noqa: BLE001  (a missing icon must never stop the page)
        pass


def main() -> None:
    st.set_page_config(
        page_title="Odds-sammenligner",
        page_icon=str(Path(__file__).with_name("static") / "icon-192.png"),
        layout="wide",
    )
    home_screen_tags()
    st.markdown(CSS, unsafe_allow_html=True)
    secrets_to_environment()
    cfg = config.load(os.environ.get("ODDSCOMPARE_CONFIG") or Path(__file__).with_name("config.yaml"))
    reference = cfg.reference.source
    reference_name = dashboard.BOOKMAKERS.get(cfg.reference.bookmaker, cfg.reference.bookmaker)
    competitors = (
        [f"{reference}:{key}" for key in cfg.reference.the_odds_api.competitors]
        if reference == "the_odds_api"
        else []
    )
    conn = db.connect(cfg.database)
    refresh_norsk_tipping(cfg, conn)
    now = datetime.now(UTC)
    stale_after = timedelta(minutes=cfg.stale_after_minutes)

    st.title("Odds-sammenligner")
    st.caption(
        f"Norsk Tipping mot margin-fri referanse ({SOURCE_NAMES.get(reference, reference)}: {reference_name})"
    )

    with st.sidebar:
        st.header("Filtre")
        order = st.selectbox("Sorter etter", list(dashboard.SORTS))
        window = st.radio("Tidsvindu", dashboard.WINDOWS, index=2, horizontal=True)
        method = st.selectbox("Marginfjerning", calc.METHODS, index=calc.METHODS.index(cfg.margin_method))
        all_cards = dashboard.load_cards(
            conn, reference, method, now, dashboard.window_end(window, now), competitors
        )
        leagues = st.multiselect("Liga", sorted({c.league for c in all_cards}), placeholder="Alle ligaer")
        min_ev = st.slider("Minimum EV", -20.0, 20.0, 0.0, 0.5, format="%.1f %%") / 100
        show_all = st.toggle("Vis alle kamper", help="Også kamper under minimum EV og uten referanseodds")
        reference_panel(cfg, conn, reference)

    for row in dashboard.fetch_status(conn):
        name = SOURCE_NAMES.get(row["source"], row["source"])
        if row["status"] != "ok":
            st.error(
                f"{name}: siste henting {local(db.parse_iso(row['started_at_utc']))} feilet: {row['error']}"
            )
        elif row["source"] == dashboard.NT:
            last = db.parse_iso(row["started_at_utc"])
            if now - last > stale_after:
                st.warning(f"{name}: siste vellykkede henting var {local(last)}. Kjører `oddscompare run`?")

    matches_tab, my_bets_tab, unmatched_tab = st.tabs(["Kamper", "Mine spill", "Umatchede kamper"])
    with matches_tab:
        cards = dashboard.sort_cards(dashboard.filter_cards(all_cards, leagues, min_ev, show_all), order)
        stats = dashboard.summary([c for c in all_cards if not leagues or c.league in leagues])
        top = st.columns(3)
        top[0].metric("Kamper", stats["matches"])
        top[1].metric("Med EV > 0", stats["positive"])
        top[2].metric(
            "Snittmargin NT / referanse", f"{percent(stats['nt_margin'])} / {percent(stats['ref_margin'])}"
        )
        if not all_cards:
            st.info("Ingen kamper i databasen for dette tidsvinduet. Kjør `oddscompare fetch` først.")
        elif not cards:
            st.info("Ingen kamper med EV over minimum. Senk minimum EV eller slå på «Vis alle kamper».")
        shown = st.session_state.get("shown", PAGE_SIZE)
        for start in range(0, min(len(cards), shown), 2):
            columns = st.columns(2)
            for column, card in zip(columns, cards[start : start + 2], strict=False):
                with column.container(border=True):
                    st.markdown(
                        card_html(card, now, stale_after, reference_name),
                        unsafe_allow_html=True,
                    )
                    if card.competitors:
                        with st.expander(f"Konkurrentenes odds ({len(card.competitors)})"):
                            st.markdown(books_table(card), unsafe_allow_html=True)
                    with st.expander("Registrer spill"):
                        bet_form(conn, card, reference_name)
                    with st.expander("Oddsutvikling"):
                        frame = dashboard.history(conn, card.event_id, reference, method)
                        if frame["tid"].nunique() < 2:
                            st.caption("Trenger minst to hentinger for å vise utviklingen.")
                        else:
                            st.plotly_chart(
                                history_chart(frame), width="stretch", key=f"chart-{card.event_id}"
                            )
        if len(cards) > shown:
            if st.button(f"Vis flere ({len(cards) - shown} til)"):
                st.session_state["shown"] = shown + PAGE_SIZE
                st.rerun()

    with my_bets_tab:
        bets_tab(conn)

    with unmatched_tab:
        rows = dashboard.unmatched(conn, now)
        if not rows:
            st.info("Alle kommende Norsk Tipping-kamper har funnet sin referansekamp.")
        else:
            st.write(
                f"{len(rows)} kommende kamper fra Norsk Tipping fant ingen referansekamp. Mange er ligaer "
                "referansen ikke dekker. Der navnet ligner, står et forslag til alias-tabellen "
                f"(`{cfg.aliases.name}`) under: kopier det inn i filen, så matches kampen ved neste henting."
            )
            suggestions = dashboard.alias_suggestions(rows, Aliases.load(cfg.aliases), cfg.fuzzy_suggest)
            if suggestions:
                st.code(yaml.safe_dump(suggestions, allow_unicode=True, sort_keys=True), language="yaml")
            st.dataframe(
                [
                    {
                        "Avspark": local(db.parse_iso(r["kickoff_utc"])),
                        "Liga": r["league"],
                        "Norsk Tipping": f"{r['raw_home'].strip()} – {r['raw_away'].strip()}",
                        "Nærmeste referansekamp": r["best_candidate"] or "",
                        "Likhet": round(r["score"]) if r["score"] is not None else None,
                    }
                    for r in rows
                ],
                hide_index=True,
                width="stretch",
            )
    conn.close()


main()
