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


def _mtime(module) -> float | None:
    try:
        return os.path.getmtime(module.__file__)
    except (TypeError, OSError):
        return None


def forget_changed_package(package: str = "oddscompare") -> bool:
    """Streamlit Cloud pulls new code and reruns this script, but the package's modules imported before
    stay loaded, so the new app.py meets old code (an AttributeError). When a module's file changed since
    it was imported, the whole package is dropped here and imported again below. Returns whether it was."""
    loaded = {n: m for n, m in list(sys.modules.items()) if n == package or n.startswith(f"{package}.")}
    if not loaded:
        return False
    recorded = getattr(sys.modules.get(package), "_imported_mtimes", None)
    if recorded is None:  # imported by an app.py without this, or by tests: changed since the process began?
        started = _process_started()
        # The start is known to a second or so (the boot time is in whole seconds), and a file written just
        # before the process began (a formatter, then tests) must not count; new code on Streamlit Cloud
        # comes minutes or hours after the start.
        stale = started is not None and any((_mtime(m) or 0) > started + 5 for m in loaded.values())
    else:
        stale = any(_mtime(loaded[n]) != t for n, t in recorded.items() if n in loaded)
        recorded.update({n: _mtime(m) for n, m in loaded.items() if n not in recorded})  # imported later
    if stale:
        for name in loaded:
            del sys.modules[name]
    return stale


def _process_started() -> float | None:
    """When this process started (Linux), from /proc."""
    try:
        with open(f"/proc/{os.getpid()}/stat", encoding="ascii") as f:
            ticks = int(f.read().rsplit(")", 1)[1].split()[19])  # field 22, starttime
        with open("/proc/stat", encoding="ascii") as f:
            boot = next(int(line.split()[1]) for line in f if line.startswith("btime "))
        return boot + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration):
        return None


def remember_package(package: str = "oddscompare") -> None:
    loaded = {n: m for n, m in list(sys.modules.items()) if n == package or n.startswith(f"{package}.")}
    if getattr(sys.modules[package], "_imported_mtimes", None) is None:
        sys.modules[package]._imported_mtimes = {n: _mtime(m) for n, m in loaded.items()}


forget_changed_package()
try:
    import oddscompare  # noqa: F401  (installed with pip install -e .)
except ImportError:  # Streamlit Cloud installs requirements.txt only: use the package from src/
    sys.path.insert(0, str(Path(__file__).with_name("src")))

from oddscompare import bets, calc, config, dashboard, db, fetch, remote  # noqa: E402
from oddscompare.matching import Aliases  # noqa: E402
from oddscompare.sources import OUTCOMES  # noqa: E402

remember_package()

PAGE_SIZE = 24
COLOURS = {"H": "#2563eb", "U": "#7c3aed", "B": "#d97706"}
SOURCE_NAMES = {
    "norsk_tipping": "Norsk Tipping",
    "the_odds_api": "The Odds API",
    "odds_api_io": "Odds-API.io",
    "oddslink": "OddsLink",
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
.oc-stale { color: #b42318; font-weight: 600; font-size: 0.85rem; }
.oc-best { font-size: 0.85rem; margin-top: 0.4rem; }
.oc-pos { font-size: 0.78rem; opacity: 0.85; margin-top: 0.25rem; line-height: 1.25; }
.oc-pos.top { color: #1e7b34; font-weight: 600; opacity: 1; }
.oc-pos.bottom { color: #b42318; font-weight: 600; opacity: 1; }
.oc-best b { font-variant-numeric: tabular-nums; }
.oc-nt-best { color: #1e7b34; font-weight: 600; }
table.oc-books { width: 100%; border-collapse: collapse; font-size: 0.88rem; font-variant-numeric: tabular-nums; }
table.oc-books th, table.oc-books td { padding: 0.2rem 0.4rem; text-align: right; border-bottom: 1px solid rgba(128,128,128,0.25); }
table.oc-books th:first-child, table.oc-books td:first-child { text-align: left; }
table.oc-books td.top { font-weight: 700; }
table.oc-books tr.nt td { background: rgba(128,128,128,0.10); }
.oc-arb-teams { font-weight: 700; font-size: 1.05rem; line-height: 1.3; }
table.oc-arb th:nth-child(2), table.oc-arb td:nth-child(2) { text-align: left; }
.oc-arb-result { margin-top: 0.5rem; }
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
            f'<div class="oc-ev {dashboard.ev_class(ev)}">EV {percent(ev, signed=True)}</div>'
            f"{position_html(card, i)}</div>"
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
        f'<div class="oc-foot">NT-margin {percent(card.nt_margin)}{margin_place_text(card)} · referansemargin {percent(card.ref_margin)}'
        f"<br>Sist hentet: {times}</div>{warning}{missing}"
    )


def position_html(card: dashboard.Card, i: int) -> str:
    """Where Norsk Tipping's price stands among the bookmakers: «Best av 8», «Nr. 4 av 8 · −5 %», «Dårligst av 8»."""
    position = card.position(i)
    if position is None:
        return ""
    place, books, gap = position
    if place == 1:
        return f'<div class="oc-pos top">Best av {books}</div>'
    behind = f"<br>{percent(gap, signed=True)} mot beste"
    if card.nt_worst(i):
        return f'<div class="oc-pos bottom">Dårligst av {books}{behind}</div>'
    return f'<div class="oc-pos">Nr. {place} av {books}{behind}</div>'


def margin_place_text(card: dashboard.Card) -> str:
    place = card.margin_place()
    if place is None:
        return ""
    rank, books = place
    if rank == 1:
        return f" (lavest av {books})"
    if rank == books:
        return f" (høyest av {books})"
    return f" ({rank}. lavest av {books})"


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


NT_COLOUR = "#2a78d6"  # the one bookmaker the chart is about
OTHERS_COLOUR = "#a9a7a0"  # the rest, as context


def market_tab(
    cards: list[dashboard.Card], reference_name: str, competitors_at: datetime | None = None
) -> None:
    """How Norsk Tipping's odds compare with its competitors', over the matches in the filters."""
    m = dashboard.market(cards, reference_name)
    if not m.matches:
        st.info("Ingen kamper med konkurrentenes odds ennå. De kommer med når du henter referanseodds.")
        return
    margins = dict((name, value) for name, value, _ in m.margins)
    competitor_margins = [h.margin for h in m.head_to_head]
    competitors_mean = sum(competitor_margins) / len(competitor_margins) if competitor_margins else None
    st.markdown(
        f"Norsk Tipping har **beste odds på {percent(m.best_share)}** av utfallene og dårligste på "
        f"{percent(m.worst_share)}. I snitt er Norsk Tippings odds **{percent(-m.mean_gap)} lavere enn beste odds** "
        f"i markedet. Marginen er {percent(margins.get('Norsk Tipping'))}, mot {percent(competitors_mean)} i snitt "
        f"hos konkurrentene og {percent(margins.get(reference_name))} hos {reference_name}. "
        f"Grunnlaget er {m.matches} kamper med konkurrentenes odds."
    )
    if competitors_at:
        st.caption(
            f"Konkurrentenes odds er fra sist referanseodds ble hentet ({local(competitors_at)}), mens Norsk Tippings "
            "odds hentes oftere. Har oddsen flyttet seg siden, blir sammenligningen mindre presis: hent referanseodds "
            "for et ferskt bilde."
        )
    top = st.columns(4)
    top[0].metric(
        "NT har beste odds", percent(m.best_share), help="Andel av utfallene, også når prisen er delt beste"
    )
    top[1].metric(
        "NT har dårligste odds",
        percent(m.worst_share),
        help="Andel av utfallene, også når prisen er delt dårligste",
    )
    top[2].metric(
        "NT mot beste odds",
        percent(m.mean_gap, signed=True),
        help="Norsk Tippings odds mot beste odds, i snitt per utfall",
    )
    top[3].metric(
        "NT-margin / konkurrenter", f"{percent(margins.get('Norsk Tipping'))} / {percent(competitors_mean)}"
    )

    best = dashboard.nt_best(cards)
    st.markdown(f"**Her har Norsk Tipping best odds** ({len(best)} utfall, blant {m.matches} kamper)")
    if best:
        st.dataframe(
            [
                {
                    "Avspark": local(b.card.kickoff_utc),
                    "Kamp": f"{b.card.home} – {b.card.away}",
                    "Liga": b.card.league,
                    "Utfall": ("H", "U", "B")[b.outcome],
                    "NT-odds": odds_text(b.odds),
                    "Nest beste": f"{odds_text(b.runner_up_odds)} {b.runner_up}"
                    if not b.shared
                    else f"delt med {b.runner_up}",
                    "NT bedre med": percent(b.lead, signed=True) if not b.shared else "delt",
                    "Fair": odds_text(b.card.fair_odds[b.outcome]) if b.card.fair_odds else "–",
                    "EV": percent(b.ev, signed=True),
                }
                for b in best
            ],
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "Beste odds blant konkurrentene betyr ikke at spillet har verdi: EV-kolonnen sammenligner med Pinnacles "
            "fair odds. Slå på «Bare der NT har best odds» i sidepanelet for å se kortene."
        )
    else:
        st.caption("Norsk Tipping har ikke beste odds på noen utfall i dette utvalget.")

    names = [name for name, _, _ in m.margins]
    values = [value * 100 for _, value, _ in m.margins]
    labelled = {"Norsk Tipping", names[0], names[-1]}  # the one the chart is about, and the two ends
    figure = go.Figure(
        go.Bar(
            x=values,
            y=names,
            orientation="h",
            marker={
                "color": [NT_COLOUR if n == "Norsk Tipping" else OTHERS_COLOUR for n in names],
                "cornerradius": 4,
            },
            text=[f"{v:.1f} %" if n in labelled else "" for n, v in zip(names, values, strict=True)],
            textposition="outside",
            customdata=[count for _, _, count in m.margins],
            hovertemplate="%{y}: %{x:.1f} % snittmargin over %{customdata} kamper<extra></extra>",
        )
    )
    figure.update_layout(
        title={"text": "Snittmargin per bookmaker (lavere er bedre for deg)", "font": {"size": 15}},
        height=60 + 34 * len(names),
        margin={"l": 10, "r": 40, "t": 50, "b": 30},
        xaxis={"title": "Margin (%)", "rangemode": "tozero", "gridcolor": "rgba(128,128,128,0.2)"},
        yaxis={"autorange": "reversed"},
        separators=", ",
        bargap=0.35,
        showlegend=False,
    )
    st.plotly_chart(figure, width="stretch", key="market-margins")

    st.markdown("**Norsk Tipping mot hver konkurrent**, på utfallene begge har odds på")
    st.dataframe(
        [
            {
                "Konkurrent": h.name,
                "Utfall": h.outcomes,
                "NT høyere odds": percent(h.nt_higher / h.outcomes),
                "Like": percent(h.equal / h.outcomes),
                "NT lavere odds": percent(h.nt_lower / h.outcomes),
                "NT-odds i snitt": percent(h.mean_gap, signed=True),
                "Deres margin": percent(h.margin),
                "NT-margin": percent(h.nt_margin),
            }
            for h in m.head_to_head
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "«NT-odds i snitt» er Norsk Tippings odds mot konkurrentens på samme utfall: −4 % betyr at du i snitt får 4 % "
        "lavere odds hos Norsk Tipping. Marginene er regnet på de samme kampene, så de kan sammenlignes rad for rad."
    )


def either(names: list[str]) -> str:
    """«Betsson», «Betsson eller Unibet», «Betsson, Coolbet eller Unibet»."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} eller {names[-1]}"


def age_text(age: timedelta) -> str:
    """«under 1 min», «25 min», «3 t 5 min» or, from two days, «3 d 4 t»."""
    minutes = int(age.total_seconds() // 60)
    if minutes < 1:
        return "under 1 min"
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} t {minutes} min"
    days, hours = divmod(hours, 24)
    return f"{days} d {hours} t"


def prices_age(a: dashboard.Arbitrage, now: datetime, stale_after: timedelta) -> str:
    """How old the prices of a sure bet are; in red when the oldest is older than stale_after."""
    known = [moment for moment in a.fetched if moment]
    if len(known) < len(a.fetched):
        return '<div class="oc-foot">Alderen på prisene er ukjent: sjekk oddsen hos spillselskapene.</div>'
    oldest, newest = now - min(known), now - max(known)
    if oldest == newest:
        text = f"Prisene ble hentet for {age_text(oldest)} siden."
    else:
        text = f"Eldste pris ble hentet for {age_text(oldest)} siden, nyeste for {age_text(newest)} siden."
    return f'<div class="{"oc-stale" if oldest > stale_after else "oc-foot"}">{text}</div>'


def arbitrage_html(a: dashboard.Arbitrage, stake: float, now: datetime, stale_after: timedelta) -> str:
    """One sure bet: where to back each outcome and with how much, and what comes back whatever the result."""
    e = html.escape
    split = a.split(stake)
    rows = "".join(
        f"<tr><td>{label}</td><td>{e(either(names))}</td><td>{odds_text(odds)}</td>"
        f"<td>{kroner(amount)}</td><td>{kroner(back)}</td></tr>"
        for label, names, odds, amount, back in zip(
            ("H", "U", "B"), a.books, a.odds, split.stakes, split.returns, strict=True
        )
    )
    head = "<tr><th>Utfall</th><th>Spillselskap</th><th>Odds</th><th>Innsats</th><th>Utbetaling</th></tr>"
    share = split.profit / split.staked if split.staked else None
    return (
        f'<div class="oc-arb-teams">{e(a.card.home)} – {e(a.card.away)}</div>'
        f'<div class="oc-meta">{e(a.card.league)} · {local(a.card.kickoff_utc)}</div>'
        f'<table class="oc-books oc-arb">{head}{rows}</table>'
        f'<div class="oc-arb-result">Garantert utbetaling <b>{kroner(split.guaranteed)}</b> for '
        f"{kroner(split.staked)} i innsats: gevinst <b>{kroner(split.profit, signed=True)} "
        f"({percent(share, signed=True)})</b></div>{prices_age(a, now, stale_after)}"
    )


def arbitrage_tab(
    cards: list[dashboard.Card], reference_name: str, now: datetime, stale_after: timedelta
) -> None:
    """Matches where backing all three outcomes at the best prices among your bookmakers wins whatever
    the result (a sure bet), and how to split the stake."""
    books = dashboard.arbitrage_books(cards)
    if len(books) < 2:
        st.info("Ingen kamper med konkurrentenes odds ennå. De kommer med når du henter referanseodds.")
        return
    picked = st.multiselect(
        "Spillselskaper du har konto hos",
        books,
        default=dashboard.default_books(books),
        format_func=lambda s: reference_name if s == dashboard.REFERENCE else dashboard.bookmaker_name(s),
        help="Børser som Betfair er ikke med fra start: oddsen her er midt mellom kjøps- og salgsprisen, og de "
        "tar provisjon av gevinsten, så den kan ikke spilles som vist.",
    )
    stake = st.number_input("Total innsats (kr)", min_value=10, value=1000, step=100)
    sure, others = dashboard.arbitrages(cards, picked, reference_name)
    if sure:
        st.markdown(
            f"**Sikker gevinst i {len(sure)} av {len(sure) + len(others)} kamper** med odds fra spillselskapene "
            "du har valgt. Innsatsen er fordelt så hvert utfall betaler ut omtrent det samme."
        )
        for a in sure:
            with st.container(border=True):
                st.markdown(arbitrage_html(a, stake, now, stale_after), unsafe_allow_html=True)
    elif len(picked) < 2:
        st.info("Velg minst to spillselskaper: hos ett alene blir det aldri sikker gevinst.")
    else:
        st.info("Ingen sikker gevinst med spillselskapene du har valgt akkurat nå.")
        if others:
            st.markdown(
                "**Nærmest sikker gevinst**, med margin: summen av 1/odds for beste odds på hvert utfall, "
                "minus 1. Under 0 % er sikker gevinst."
            )
            st.dataframe(
                [
                    {
                        "Avspark": local(a.card.kickoff_utc),
                        "Kamp": f"{a.card.home} – {a.card.away}",
                        "Liga": a.card.league,
                        **{
                            label: f"{odds_text(odds)} {either(names)}"
                            for label, odds, names in zip(("H", "U", "B"), a.odds, a.books, strict=True)
                        },
                        "Margin": percent(a.total - 1),
                    }
                    for a in others[:5]
                ],
                hide_index=True,
                width="stretch",
            )
    st.caption(
        "Prisene kan endre seg før du rekker å spille alle tre, og de kan være gamle: konkurrentenes odds er fra "
        "sist referanseodds ble hentet. Sjekk oddsen hos hvert spillselskap før du spiller. Spillselskapene kan "
        "også annullere slike spill eller begrense kontoen din."
    )


@st.cache_resource
def bet_log_sync() -> dict:
    """Shared by every session of this app process: whether the stored bet log has been read back, and
    the digest of what was last written."""
    return {"restored": None, "digest": None, "error": None}


def sync_bet_log(conn) -> dict | None:
    """With DATABASE_URL: read the stored bet log back once per app process (after a restart the local one
    is empty), then write it whenever it changed. None without a database."""
    store = remote.store_from_env()
    if store is None:
        return None
    state = bet_log_sync()
    try:
        if state["restored"] is None:
            state["restored"] = remote.restore_bets(conn, store)
        state["digest"] = remote.backup_bets(conn, store, state["digest"])
        state["error"] = None
    except Exception as e:  # noqa: BLE001  (the bet log here still works; it is written next time)
        state["error"] = remote.safe_error(e, store.url)  # never the address or password
    return state


def bet_log_status(state: dict | None) -> None:
    if state is None:
        st.caption(
            "Spilloggen ligger bare i appen og forsvinner når den starter på nytt. Last den ned jevnlig, "
            "eller legg `DATABASE_URL` til en gratis database under «Secrets» (se README, «Varig spillogg»)."
        )
    elif state["error"]:
        restored = state["restored"] is not None
        st.warning(
            "Fikk ikke kontakt med databasen for spilloggen"
            + ("" if restored else ", så den lagrede spilloggen er ikke lest inn ennå")
            + f". Den prøves igjen ved neste klikk. ({state['error']})"
        )
    else:
        st.caption("Spilloggen lagres i databasen, og kommer tilbake når appen starter på nytt.")


def bets_tab(conn, sync: dict | None = None) -> None:
    bet_log_status(sync)
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
    elif reference == "oddslink":
        left = dashboard.credits_left(cfg.cache_dir, reference)
        if left is not None:
            lines.append(f"Forespørsler igjen denne måneden: {left}.")
        lines.append("Én forespørsel henter alle ligaene.")
    st.caption(" ".join(lines))
    if st.button(
        "Hent referanseodds",
        type="primary",
        width="stretch",
        disabled=request_cfg is not cfg and not leagues,
    ):
        fetch_reference(request_cfg, "sidebar")
    reference_result("sidebar")


def update_buttons(cfg: config.Config, conn, reference: str, reference_name: str) -> None:
    """Both fetches on the page, where a phone shows them (it hides the sidebar), with when each was last."""
    nt_last = dashboard.last_success(conn, dashboard.NT)
    ref_last = dashboard.last_success(conn, reference)
    n = len(cfg.reference.the_odds_api.leagues) if reference == "the_odds_api" else None
    cost = {"the_odds_api": f" (opptil {n} kreditter)", "oddslink": " (1 forespørsel)"}.get(reference, "")
    unit = "forespørsler" if reference == "oddslink" else "kreditter"
    credits = dashboard.credits_left(cfg.cache_dir, reference)
    left, right = st.columns(2)
    if left.button(
        "Oppdater Norsk Tipping",
        width="stretch",
        help=f"Gratis. Skjer også av seg selv når oddsen er eldre enn {cfg.interval_minutes:g} minutter.",
    ):
        refresh_norsk_tipping(cfg, conn, force=True)
        st.rerun()
    if right.button(
        f"Oppdater referanseodds{cost}",
        type="primary",
        width="stretch",
        help=f"{reference_name} og konkurrentene, for alle ligaer."
        + (" Færre ligaer kan velges i menyen (››)." if reference == "the_odds_api" else "")
        + " En ny henting innen 5 minutter bruker forrige svar og koster ingenting.",
    ):
        fetch_reference(cfg, "page")
    parts = [
        f"Norsk Tipping: {local(nt_last) if nt_last else 'aldri hentet'}",
        f"{reference_name}: {local(ref_last) if ref_last else 'aldri hentet'}",
    ]
    if credits is not None:
        parts.append(f"{credits} {unit} igjen denne måneden")
    st.caption(" · ".join(parts))


def fetch_reference(request_cfg: config.Config, where: str) -> None:
    """Buy reference odds now; the result is shown where the button was (the sidebar or the page)."""
    with st.spinner("Henter referanseodds …"):
        report = fetch.run_once(request_cfg, include_reference=True)
    st.session_state["reference_result"] = (
        all(s.status == "ok" for s in report.sources),
        fetch.summary(report),
        where,
    )
    st.rerun()


def reference_result(where: str) -> None:
    if "reference_result" in st.session_state:
        ok, text, shown_at = st.session_state["reference_result"]
        if shown_at == where:
            (st.success if ok else st.error)(text.replace("\n", "  \n"))


SECRETS_HELP = (
    "Gå til «Manage app» nederst til høyre → ⋮ → «Settings» → «Secrets», og skriv nøkkelen på én linje, "
    'med anførselstegn: `THE_ODDS_API_KEY = "nøkkelen"`. Trykk «Save», så starter appen på nytt.'
)


def secrets_to_environment() -> str | None:
    """API keys from Streamlit's secrets (Streamlit Cloud), for the code that reads them from the environment.

    A key under a heading such as [secrets] counts too. Returns what to tell the user when the secrets
    could not be read (a value without quotes is not valid TOML), else None."""
    try:
        config.apply_secrets(st.secrets)
    except Exception as e:  # noqa: BLE001  (no secrets at all: .env is used instead)
        if "pars" in str(e).lower():
            return f"Streamlits «Secrets» kunne ikke leses. {SECRETS_HELP}"
    return None


@st.cache_resource
def fetch_lock() -> threading.Lock:
    """One Norsk Tipping fetch at a time, however many people have the page open."""
    return threading.Lock()


def refresh_norsk_tipping(
    cfg: config.Config, conn, force: bool = False, spinner: str = "Henter Norsk Tippings odds …"
) -> bool:
    """Fetch Norsk Tipping when its odds are older than interval_minutes (no fetcher running beside the page),
    or now with force (the source still asks Norsk Tipping at most once per min_interval_minutes). Returns
    whether new odds came."""
    last = dashboard.last_success(conn, dashboard.NT)
    if not force and last and datetime.now(UTC) - last < timedelta(minutes=cfg.interval_minutes):
        return False
    lock = fetch_lock()
    if not lock.acquire(blocking=False):
        return False
    try:
        with st.spinner(spinner):
            report = fetch.run_once(cfg)
    finally:
        lock.release()
    return bool(report.sources) and report.sources[0].status == "ok"


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
    secrets_problem = secrets_to_environment()
    cfg = config.load(os.environ.get("ODDSCOMPARE_CONFIG") or Path(__file__).with_name("config.yaml"))
    reference = cfg.reference.source
    reference_name = dashboard.BOOKMAKERS.get(cfg.reference.bookmaker, cfg.reference.bookmaker)
    competitors = fetch.competitor_sources(cfg)  # the same list the fetch stores, for OddsLink too
    conn = db.connect(cfg.database)
    sync = sync_bet_log(conn)  # first: after a restart the bet log comes back before anything shows it
    # With odds to show, the page shows them at once and fetches newer ones at the end, then redraws;
    # only an empty database (a new or restarted app) waits for Norsk Tipping first.
    had_odds = dashboard.last_success(conn, dashboard.NT) is not None
    if not had_odds:
        refresh_norsk_tipping(cfg, conn)
    now = datetime.now(UTC)
    stale_after = timedelta(minutes=cfg.stale_after_minutes)

    st.title("Odds-sammenligner")
    st.caption(
        f"Norsk Tipping mot margin-fri referanse ({SOURCE_NAMES.get(reference, reference)}: {reference_name})"
    )
    if secrets_problem:
        st.error(secrets_problem)

    with st.sidebar:
        st.header("Filtre")
        order = st.selectbox("Sorter etter", list(dashboard.SORTS))
        window = st.radio("Tidsvindu", dashboard.WINDOWS, index=2, horizontal=True)
        method = st.selectbox("Marginfjerning", calc.METHODS, index=calc.METHODS.index(cfg.margin_method))
        all_cards = dashboard.load_cards(
            conn, reference, method, now, dashboard.window_end(window, now), competitors
        )
        leagues = st.multiselect("Liga", sorted({c.league for c in all_cards}), placeholder="Alle ligaer")
        value_only = st.toggle("Bare verdispill", help="Bare kamper med EV over minimum EV. Av: alle kamper.")
        min_ev = (
            st.slider("Minimum EV", -20.0, 20.0, 0.0, 0.5, format="%.1f %%", disabled=not value_only) / 100
        )
        show_all = not value_only
        nt_best_only = st.toggle(
            "Bare der NT har best odds",
            help="Kamper der Norsk Tipping har beste odds på minst ett utfall blant konkurrentene, uansett EV",
        )
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

    matches_tab, market_tab_, arbitrage_tab_, my_bets_tab, unmatched_tab = st.tabs(
        ["Kamper", "NT mot markedet", "Sikker gevinst", "Mine spill", "Umatchede kamper"]
    )
    with matches_tab:
        # Before any reference odds are fetched here, nothing has EV, and the EV filter would hide every match:
        # Norsk Tipping's odds are shown instead (the buttons are on the page; phones hide the sidebar).
        no_ev_yet = bool(all_cards) and all(c.ev is None for c in all_cards)
        if no_ev_yet:
            st.info(
                "Ingen referanseodds er hentet her ennå, så EV kan ikke regnes ut. Under ser du Norsk Tippings "
                "odds for alle kamper. Trykk «Oppdater referanseodds», eller velg færre ligaer under "
                "«Referanseodds» i menyen (›› øverst til venstre på mobil)."
            )
        update_buttons(cfg, conn, reference, reference_name)
        reference_result("page")
        query = st.text_input("Søk etter lag", placeholder="For eksempel Brann, Bodø/Glimt eller Arsenal")
        cards = dashboard.sort_cards(
            dashboard.search_cards(
                dashboard.filter_cards(all_cards, leagues, min_ev, show_all or no_ev_yet, nt_best_only), query
            ),
            order,
        )
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
            st.info(
                f"Ingen kamper med «{query.strip()}» i tidsvinduet."
                if query.strip()
                else "Ingen kamper med EV over minimum. Senk minimum EV eller slå av «Bare verdispill»."
            )
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
                    # Drawn only when asked for: a chart for every card made each run about twice as slow.
                    if st.toggle("Vis oddsutvikling", key=f"history-{card.event_id}"):
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

    with market_tab_:
        market_tab(
            [c for c in all_cards if not leagues or c.league in leagues],
            reference_name,
            dashboard.last_success(conn, reference),
        )

    with arbitrage_tab_:
        arbitrage_tab(
            [c for c in all_cards if not leagues or c.league in leagues], reference_name, now, stale_after
        )

    with my_bets_tab:
        bets_tab(conn, sync)

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
    sync_bet_log(conn)  # a change made in this run (one followed by st.rerun() is written on the next)
    fresh = had_odds and refresh_norsk_tipping(cfg, conn, spinner="Oppdaterer Norsk Tippings odds …")
    conn.close()
    if fresh:
        st.rerun()  # draw the page again with the new odds


main()
