from __future__ import annotations

import ipaddress
import random
import threading
import unicodedata
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

try:
    import geoip2.database
except Exception as exc:  # pragma: no cover
    geoip2 = None
    GEOIP2_IMPORT_ERROR = repr(exc)
else:
    GEOIP2_IMPORT_ERROR = ""


@dataclass(frozen=True)
class BalancedHosts:
    vod_host: str
    live_host: str
    client_ip: str | None = None
    asn: int | None = None
    city: str | None = None
    decision: str = "default"


def _strip_accents(value: str) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _normalize_city(value: str | None) -> str:
    return _strip_accents((value or "").strip()).casefold()


def _pick_one(value: str | list[str] | tuple[str, ...]) -> str:
    if isinstance(value, (list, tuple)):
        return random.choice(list(value))
    return value


def _iter_forwarded_for(value: str | None):
    if not value:
        return
    for part in value.split(","):
        ip = part.strip()
        if ip:
            yield ip


def _pick_client_ip(request) -> str | None:
    # Orden de preferencia (cuando hay reverse proxies/CDNs):
    # 1) CF-Connecting-IP / True-Client-IP / X-Real-IP (una sola IP)
    # 2) X-Forwarded-For (lista)
    # 3) REMOTE_ADDR
    candidates: list[str] = []

    for header in ("HTTP_CF_CONNECTING_IP", "HTTP_TRUE_CLIENT_IP", "HTTP_X_REAL_IP"):
        value = (request.META.get(header) or "").strip()
        if value:
            candidates.append(value)

    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    candidates.extend(list(_iter_forwarded_for(xff)))

    remote_addr = (request.META.get("REMOTE_ADDR") or "").strip()
    if remote_addr:
        candidates.append(remote_addr)

    for raw in candidates:
        try:
            ip_obj = ipaddress.ip_address(raw)
        except ValueError:
            continue

        # Preferir IPs públicas/globales (evita quedarnos con 10.x/192.168.x si hay proxy)
        if ip_obj.is_global:
            return str(ip_obj)

    # Si no hay global, al menos devolver algo válido
    for raw in candidates:
        try:
            ipaddress.ip_address(raw)
            return raw
        except ValueError:
            continue

    return None


# ---- Config (equivalente al PHP) ----

_MOVISTAR_ASNS = {
    7418,
    52489,
    52396,
    19196,
    16629,
    27680,
    263208,
    15311,
}

_CLARO_ASNS = {27995, 6535, 6429}

_INTERNEXA_ASNS = {52280}

_MANQUEHUE_ASNS = {18822, 14259, 270059, 263184}

_TELSUR_ASNS = {14117}

_VTR_ASNS = {22047, 19632}


def _default_hosts() -> BalancedHosts:
    host_default = getattr(settings, "WOWZA_HOST_DEFAULT", "scl.edge.grupoz.cl")
    return BalancedHosts(vod_host=host_default, live_host=host_default, decision="default")


def _fallback_hosts(reason: str, *, client_ip: str | None = None) -> BalancedHosts:
    if not bool(getattr(settings, "CDN_BALANCER_FALLBACK_TO_CDN", True)):
        defaults = _default_hosts()
        return BalancedHosts(
            vod_host=defaults.vod_host,
            live_host=defaults.live_host,
            client_ip=client_ip,
            decision=f"default:{reason}",
        )

    return BalancedHosts(
        vod_host=getattr(settings, "CDN_BALANCER_FALLBACK_VOD_HOST", "claro-vtrlolla-vod.cl.cdnz.cl"),
        live_host=getattr(settings, "CDN_BALANCER_FALLBACK_LIVE_HOST", "claro.02.cl.cdnz.cl"),
        client_ip=client_ip,
        decision=f"fallback_cdn:{reason}",
    )


def _select_by_asn_and_city(asn: int | None, city_es: str | None) -> BalancedHosts:
    city = _normalize_city(city_es)

    # VOD hosts
    vod_entel = "entel-01-vtrlolla-vod.cl.cdnz.cl"
    vod_claro = "claro-vtrlolla-vod.cl.cdnz.cl"
    vod_mov_antof = "telanto01-vtrlolla-vod.cl.cdnz.cl"
    vod_mov_conce = "telconce01-vtrlolla-vod.cl.cdnz.cl"
    vod_mov_punta = "telpunta01-vtrlolla-vod.cl.cdnz.cl"
    vod_mov_stgo = "telsantin1-vtrlolla-vod.cl.cdnz.cl"
    vod_manquehue = "manquehue-01-vtrlolla-vod.cl.cdnz.cl"
    vod_telsur = ["telsur01-vtrlolla-vod.cl.cdnz.cl", "telsur02-vtrlolla-vod.cl.cdnz.cl"]
    vod_vtr = ["vtrcache-vtrlolla-vod.cl.cdnz.cl", "vtrcache02-vtrlolla-vod.cl.cdnz.cl"]
    vod_pitchile = "pitchile-vtrlolla-vod.cl.cdnz.cl"
    vod_internexa = "internexa-vtrlolla-vod.cl.cdnz.cl"
    vod_default = [
        "internexa-vtrlolla-vod.cl.cdnz.cl",
        "claro-vtrlolla-vod.cl.cdnz.cl",
        "florida01-vtrlolla-vod.cl.cdnz.cl",
        "pitchile-vtrlolla-vod.cl.cdnz.cl",
    ]

    # LIVE hosts
    live_claro = "claro.02.cl.cdnz.cl"
    live_mov_antof = "telanto01.02.cl.cdnz.cl"
    live_mov_conce = "telconce01.02.cl.cdnz.cl"
    live_mov_punta = "telpunta01.02.cl.cdnz.cl"
    live_mov_stgo = "telsantin1.02.cl.cdnz.cl"
    live_manquehue = "manquehue-01.02.cl.cdnz.cl"
    live_telsur = ["telsur01.02.cl.cdnz.cl", "telsur02.02.cl.cdnz.cl"]
    live_vtr = "vtrcache.02.cl.cdnz.cl"
    live_internexa = "internexa.02.cl.cdnz.cl"
    live_default = ["internexa.02.cl.cdnz.cl", "claro.02.cl.cdnz.cl"]

    if asn in _MOVISTAR_ASNS:
        # Mapeo por ciudad (equivalente al PHP, con fix para Punta Arenas)
        if city in {"santiago de chile", "santiago"}:
            return BalancedHosts(vod_host=vod_mov_stgo, live_host=live_mov_stgo, asn=asn, city=city_es, decision="movistar:santiago")
        if city == "antofagasta":
            return BalancedHosts(vod_host=vod_mov_antof, live_host=live_mov_antof, asn=asn, city=city_es, decision="movistar:antofagasta")
        if city in {"concepcion", "concepción"}:
            return BalancedHosts(vod_host=vod_mov_conce, live_host=live_mov_conce, asn=asn, city=city_es, decision="movistar:concepcion")
        if city == "punta arenas":
            return BalancedHosts(vod_host=vod_mov_punta, live_host=live_mov_punta, asn=asn, city=city_es, decision="movistar:punta_arenas")
        return BalancedHosts(vod_host=vod_pitchile, live_host=_pick_one(live_default), asn=asn, city=city_es, decision="movistar:default")

    if asn in _CLARO_ASNS:
        return BalancedHosts(vod_host=vod_claro, live_host=live_claro, asn=asn, city=city_es, decision="claro")

    if asn in _INTERNEXA_ASNS:
        return BalancedHosts(vod_host=vod_internexa, live_host=live_internexa, asn=asn, city=city_es, decision="internexa")

    if asn in _MANQUEHUE_ASNS:
        return BalancedHosts(vod_host=vod_manquehue, live_host=live_manquehue, asn=asn, city=city_es, decision="manquehue")

    if asn in _TELSUR_ASNS:
        return BalancedHosts(vod_host=_pick_one(vod_telsur), live_host=_pick_one(live_telsur), asn=asn, city=city_es, decision="telsur")

    if asn in _VTR_ASNS:
        return BalancedHosts(vod_host=_pick_one(vod_vtr), live_host=live_vtr, asn=asn, city=city_es, decision="vtr")

    # Default
    return BalancedHosts(vod_host=_pick_one(vod_default), live_host=_pick_one(live_default), asn=asn, city=city_es, decision="default:geo")


_readers_lock = threading.Lock()
_city_reader = None
_asn_reader = None
_city_reader_path = None
_asn_reader_path = None


def _get_reader(kind: str, db_path: str):
    global _city_reader, _asn_reader, _city_reader_path, _asn_reader_path

    if not db_path:
        return None

    if geoip2 is None:  # geoip2 no instalado
        return None

    with _readers_lock:
        if kind == "city":
            if _city_reader is None or _city_reader_path != db_path:
                try:
                    if _city_reader is not None:
                        _city_reader.close()
                except Exception:
                    pass
                _city_reader = geoip2.database.Reader(db_path)
                _city_reader_path = db_path
            return _city_reader

        if kind == "asn":
            if _asn_reader is None or _asn_reader_path != db_path:
                try:
                    if _asn_reader is not None:
                        _asn_reader.close()
                except Exception:
                    pass
                _asn_reader = geoip2.database.Reader(db_path)
                _asn_reader_path = db_path
            return _asn_reader

    return None


def _lookup_asn_city(client_ip: str) -> tuple[int | None, str | None]:
    city_db = getattr(settings, "CDN_BALANCER_CITY_DB_PATH", "")
    asn_db = getattr(settings, "CDN_BALANCER_ASN_DB_PATH", "")

    asn = None
    city_name_es = None

    try:
        asn_reader = _get_reader("asn", asn_db)
        if asn_reader is not None:
            asn_resp = asn_reader.asn(client_ip)
            asn = getattr(asn_resp, "autonomous_system_number", None)
    except Exception:
        asn = None

    try:
        city_reader = _get_reader("city", city_db)
        if city_reader is not None:
            city_resp = city_reader.city(client_ip)
            city_name_es = None
            try:
                city_name_es = city_resp.city.names.get("es")
            except Exception:
                city_name_es = None
    except Exception:
        city_name_es = None

    return asn, city_name_es


def get_balanced_hosts_for_request(request) -> BalancedHosts:
    """Devuelve hosts VOD/LIVE balanceados según IP→(ASN, Ciudad).

    - No lanza excepciones: si falta geoip2/mmdb, cae al CDN fallback configurable.
    - Cachea por IP para bajar costo.
    """

    client_ip = _pick_client_ip(request)

    if not bool(getattr(settings, "CDN_BALANCER_ENABLED", True)):
        defaults = _default_hosts()
        return BalancedHosts(
            vod_host=defaults.vod_host,
            live_host=defaults.live_host,
            client_ip=client_ip,
            decision="disabled",
        )

    if not client_ip:
        return _fallback_hosts("no_ip", client_ip=None)

    # Si no está geoip2, usar CDN fallback para no volver al origen.
    if geoip2 is None:
        return _fallback_hosts("no_geoip2", client_ip=client_ip)

    # Si no hay DBs configuradas, usar CDN fallback.
    if not getattr(settings, "CDN_BALANCER_CITY_DB_PATH", "") and not getattr(settings, "CDN_BALANCER_ASN_DB_PATH", ""):
        return _fallback_hosts("no_mmdb", client_ip=client_ip)

    cache_ttl = int(getattr(settings, "CDN_BALANCER_CACHE_TTL_SECONDS", 3600))
    cache_key = f"cdn_balancer:v1:{client_ip}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and cached.get("vod_host") and cached.get("live_host"):
        return BalancedHosts(
            vod_host=cached["vod_host"],
            live_host=cached["live_host"],
            client_ip=client_ip,
            asn=cached.get("asn"),
            city=cached.get("city"),
            decision=cached.get("decision", "cache"),
        )

    asn, city = _lookup_asn_city(client_ip)
    # Si no pudimos resolver nada, usar CDN fallback para no volver al origen.
    if asn is None and not (city and str(city).strip()):
        selected = _fallback_hosts("no_geo_match", client_ip=client_ip)
    else:
        selected = _select_by_asn_and_city(asn, city)
    selected = BalancedHosts(
        vod_host=selected.vod_host,
        live_host=selected.live_host,
        client_ip=client_ip,
        asn=selected.asn,
        city=selected.city,
        decision=selected.decision,
    )

    cache.set(
        cache_key,
        {
            "vod_host": selected.vod_host,
            "live_host": selected.live_host,
            "asn": selected.asn,
            "city": selected.city,
            "decision": selected.decision,
        },
        cache_ttl,
    )

    return selected
