"""BankID login and account creation pages, the development simulator, and the page where a
person approves an AI agent's access request (device authorization flow)."""

from __future__ import annotations

import sqlite3
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from starlette.datastructures import FormData

from . import identity, users
from .deps import base_url, client_ip, get_conn
from .errors import AppError, NotFound, RateLimited, ValidationProblem
from .templating import SESSION_COOKIE, current_user, redirect, render, safe_next
from .web import check_csrf, get_form, login_redirect

router = APIRouter(include_in_schema=False)
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Form = Annotated[FormData, Depends(get_form)]
PENDING_COOKIE = "ft_pending"


def _provider(request: Request) -> identity.Provider:
    provider = request.app.state.identity_provider
    if provider is None:
        raise NotFound("BankID er ikke slått på.")
    return provider


def _redirect_uri(request: Request) -> str:
    return f"{base_url(request)}/bankid/callback"


def start_session(
    request: Request, conn: sqlite3.Connection, user: users.User, target: str, flash: str
) -> Response:
    token = users.create_session(conn, user.id)
    response = redirect(target, flash=flash)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=users.SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.cookies_secure,
        path="/",
    )
    return response


@router.get("/bankid/start")
def bankid_start(request: Request, conn: Conn) -> Response:
    provider = _provider(request)
    settings = request.app.state.settings
    decision = request.app.state.limiter.hit(
        "auth", client_ip(request), settings.rate_limit_auth_per_10min, 600
    )
    if not decision.allowed:
        raise RateLimited(
            "For mange innloggingsforsøk. Vent litt og prøv igjen.", retry_after=decision.reset_in
        )
    target = safe_next(request.query_params.get("neste"), "/min-side")
    url = identity.start_login(conn, provider, _redirect_uri(request), target)
    return redirect(url, status=302)


@router.get("/bankid/callback")
def bankid_callback(request: Request, conn: Conn) -> Response:
    provider = _provider(request)
    params = request.query_params
    if params.get("error"):
        return redirect("/logg-inn", flash="BankID-innloggingen ble avbrutt.")
    state, code = params.get("state", ""), params.get("code", "")
    try:
        verified, return_to = identity.finish_login(conn, provider, _redirect_uri(request), state, code)
    except AppError as exc:
        return redirect("/logg-inn", flash=exc.message)
    hashed = identity.identity_hash(request.app.state.secret_key, verified)
    user = users.get_user_by_identity(conn, hashed)
    target = safe_next(return_to, "/min-side")
    if user is not None:
        if user.banned_at:
            return redirect("/", flash="Kontoen din er stengt av en moderator.")
        return start_session(request, conn, user, target, f"Velkommen tilbake, {user.name}!")
    token = identity.create_pending(conn, verified, hashed, provider.via, target)
    response = redirect("/registrer/fullfor")
    response.set_cookie(
        PENDING_COOKIE,
        token,
        max_age=identity.PENDING_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=request.app.state.settings.cookies_secure,
        path="/",
    )
    return response


@router.get("/registrer/fullfor")
def complete_registration_page(request: Request, conn: Conn) -> Response:
    pending = identity.get_pending(conn, request.cookies.get(PENDING_COOKIE))
    if pending is None:
        return redirect("/registrer", flash="Logg inn med BankID først.")
    return render(
        request, conn, "complete_registration.html", {"pending": pending, "values": {}, "errors": {}}
    )


@router.post("/registrer/fullfor")
def complete_registration(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    token = request.cookies.get(PENDING_COOKIE, "")
    pending = identity.get_pending(conn, token)
    if pending is None:
        return redirect("/registrer", flash="Økten er utløpt. Logg inn med BankID på nytt.")
    values = {"email": str(form.get("email") or "")}
    errors: dict[str, str] = {}
    if not form.get("terms"):
        errors["terms"] = "Du må godta vilkårene."
    if not errors:
        try:
            user = users.create_user(
                conn,
                values["email"],
                pending["display_name"],
                None,
                identity_hash=pending["identity_hash"],
                verified_name=pending["verified_name"],
                verified_via=pending["verified_via"],
            )
        except ValidationProblem as exc:
            errors = {str(e["field"]): str(e["message"]) for e in exc.errors}
        except AppError as exc:
            errors = {"email": exc.message}
    if errors:
        context = {"pending": pending, "values": values, "errors": errors}
        return render(request, conn, "complete_registration.html", context, status=422)
    identity.delete_pending(conn, token)
    settings = request.app.state.settings
    response = start_session(
        request,
        conn,
        user,
        pending["return_to"] or "/min-side",
        f"Velkommen til {settings.site_name}, {user.name}!",
    )
    response.delete_cookie(PENDING_COOKIE, path="/")
    return response


# --- Development simulator ----------------------------------------------------------------------


def _simulator(request: Request) -> identity.SimulatedProvider:
    provider = request.app.state.identity_provider
    if not isinstance(provider, identity.SimulatedProvider):
        raise NotFound("Siden finnes ikke.")
    return provider


@router.get("/bankid/simulator")
def simulator_page(request: Request, conn: Conn) -> Response:
    _simulator(request)
    state = request.query_params.get("state", "")
    if not identity.login_nonce(conn, state):
        return redirect("/logg-inn", flash="Innloggingen er utløpt. Prøv igjen.")
    return render(request, conn, "bankid_simulator.html", {"state": state, "errors": {}, "values": {}})


@router.post("/bankid/simulator")
def simulator_submit(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    provider = _simulator(request)
    state = str(form.get("state") or "")
    nonce = identity.login_nonce(conn, state)
    if not nonce:
        return redirect("/logg-inn", flash="Innloggingen er utløpt. Prøv igjen.")
    name = " ".join(str(form.get("name") or "").split())
    subject = "".join(str(form.get("subject") or "").split())
    errors = {}
    if len(name.split()) < 2:
        errors["name"] = "Skriv fornavn og etternavn."
    if not (subject.isdigit() and len(subject) == 11):
        errors["subject"] = "Testidentiteten må ha 11 siffer (som et fødselsnummer)."
    if errors:
        context = {"state": state, "errors": errors, "values": {"name": name, "subject": subject}}
        return render(request, conn, "bankid_simulator.html", context, status=422)
    code = provider.make_code(name, subject, nonce)
    return redirect("/bankid/callback?" + urlencode({"state": state, "code": code}), status=303)


# --- Agent access approval (device flow) --------------------------------------------------------


@router.get("/koble-til")
def device_page(request: Request, conn: Conn) -> Response:
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    code = request.query_params.get("kode", "")
    grant = identity.pending_grant(conn, code) if code else None
    return render(
        request, conn, "device.html", {"grant": grant, "code": code, "invalid": bool(code and not grant)}
    )


@router.post("/koble-til")
def device_decision(request: Request, conn: Conn, form: Form) -> Response:
    check_csrf(request, form)
    user = current_user(request, conn)
    if user is None:
        return login_redirect(request)
    code = str(form.get("kode") or "")
    if form.get("decision") not in ("approve", "deny"):
        return redirect(f"/koble-til?kode={identity.normalize_user_code(code) or code}")
    approve = form.get("decision") == "approve"
    if not identity.decide_grant(conn, code, user.id, approve):
        return redirect("/koble-til", flash="Koden er ugyldig eller utløpt. Be agenten om en ny kode.")
    if approve:
        return redirect(
            "/min-side#nokler", flash="Agenten har fått tilgang. Du kan trekke tilgangen tilbake her."
        )
    return redirect("/", flash="Forespørselen er avvist.")
