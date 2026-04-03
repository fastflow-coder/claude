"""
Website quality scoring.

Primary: Ollama local LLM (llama3 / mistral / phi3).
Fallback: Deterministic rule-based scorer (no external dependencies).
"""

import json
import re

import httpx

from lead_qualifier.config import OLLAMA_MODEL, OLLAMA_TIMEOUT_S, OLLAMA_URL

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_SYSTEM_PROMPT = (
    "Sen bir dijital pazarlama uzmanısın. "
    "Sana bir işletmenin web sitesi analiz verisi verilecek. "
    "Sadece JSON formatında yanıt ver, başka hiçbir şey yazma."
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_website(analysis: dict) -> dict:
    """
    Try Ollama first; fall back to rule-based scorer.
    Returns a dict with: score (0–100), priority, main_issues, sales_pitch, reachable.
    """
    result = _ollama_score(analysis)
    if result is None:
        result = _rule_score(analysis)
    result["reachable"] = analysis.get("reachable", False)
    return result


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


def _ollama_score(analysis: dict) -> dict | None:
    prompt = _build_prompt(analysis)
    try:
        resp = httpx.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "system": _SYSTEM_PROMPT,
                "stream": False,
            },
            timeout=OLLAMA_TIMEOUT_S,
        )
        raw = resp.json().get("response", "")
        m = _JSON_RE.search(raw)
        if m:
            data = json.loads(m.group())
            # Validate expected keys exist
            if {"score", "priority", "main_issues", "sales_pitch"} <= data.keys():
                data["score"] = int(data["score"])
                return data
    except Exception:
        pass
    return None


def _build_prompt(a: dict) -> str:
    return f"""
Aşağıdaki web sitesi analiz verilerini değerlendir ve JSON olarak puanla:

URL: {a.get('url', 'N/A')}
Ulaşılabilir: {a.get('reachable', False)}
Yükleme süresi: {a.get('load_time_ms', 'N/A')} ms
Meta description var mı: {a.get('has_meta_description', False)}
Mobil viewport var mı: {a.get('has_viewport', False)}
HTTPS kullanıyor mu: {a.get('is_https', False)}
Telefon numarası görünüyor mu: {a.get('has_phone', False)}
Site içeriğindeki en yeni yıl: {a.get('copyright_year', 'Bulunamadı')}
Site içeriği özeti: {a.get('html_snippet', '')[:500]}

Şu kriterlere göre puan ver (0-100, yüksek puan = yeni siteye daha çok ihtiyaç var):
- Yavaş yükleme (>3000ms): +20 puan
- Meta description yok: +15 puan
- Mobil uyumsuz: +25 puan
- HTTP (HTTPS değil): +15 puan
- 2020 öncesi içerik: +15 puan
- Ulaşılamıyor: +10 puan

Yanıtını SADECE bu JSON formatında ver:
{{
  "score": <0-100 arası integer>,
  "priority": "<HIGH|MEDIUM|LOW>",
  "main_issues": ["sorun1", "sorun2"],
  "sales_pitch": "<tek cümle Türkçe satış argümanı>"
}}
"""


# ---------------------------------------------------------------------------
# Rule-based fallback
# ---------------------------------------------------------------------------


def _rule_score(analysis: dict) -> dict:
    score = 0
    issues: list[str] = []

    if not analysis.get("reachable"):
        score += 10
        issues.append("Siteye ulaşılamıyor")
    if not analysis.get("has_viewport"):
        score += 25
        issues.append("Mobil uyumsuz")
    if not analysis.get("has_meta_description"):
        score += 15
        issues.append("SEO eksik (meta description yok)")
    if not analysis.get("is_https"):
        score += 15
        issues.append("HTTPS kullanmıyor")

    load_ms = analysis.get("load_time_ms") or 0
    if load_ms > 3000:
        score += 20
        issues.append(f"Yavaş yükleme ({load_ms} ms)")
    elif load_ms > 5000:
        score += 30  # extra weight

    year = analysis.get("copyright_year")
    if year and year < 2020:
        score += 15
        issues.append(f"Eski içerik ({year})")

    score = min(score, 100)
    priority = "HIGH" if score >= 50 else "MEDIUM" if score >= 25 else "LOW"

    return {
        "score": score,
        "priority": priority,
        "main_issues": issues,
        "sales_pitch": _default_pitch(issues),
    }


def _default_pitch(issues: list[str]) -> str:
    if not issues:
        return "Web siteniz genel olarak iyi durumda."
    top = issues[0]
    if "Mobil" in top:
        return "Müşterilerinizin çoğu telefonda geziniyor — mobil uyumlu bir site satışlarınızı artırır."
    if "SEO" in top:
        return "Google'da üst sıralara çıkmak için SEO optimizasyonuna ihtiyacınız var."
    if "HTTPS" in top:
        return "HTTPS olmayan siteler tarayıcılarda 'Güvenli değil' uyarısı gösterir — müşteriler kaçar."
    if "Yavaş" in top:
        return "Yavaş açılan siteler ziyaretçileri kaybettirir; hız optimizasyonu kritik."
    return "Web siteniz modernizasyona ihtiyaç duyuyor."
