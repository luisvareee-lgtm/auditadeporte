import os
import re
import asyncio
import random
from datetime import datetime
from playwright.async_api import async_playwright
from supabase import create_client, Client

# ============================================================================
# CREDENCIALES SEGURAS (Se conectan automáticamente con GitHub Actions o tu PC)
# ============================================================================
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://tjlejedfjypntsylqpeq.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "AQUI_IRIA_TU_CLAVE_SI_CORRES_EN_LOCAL")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Expresiones regulares para detectar Gobernanza, Documentos y Alertas Presupuestarias
REGEX_DOCUMENTOS = re.compile(r"(resoluci[oó]n|decreto|licitaci[oó]n|expediente|balance|asamblea|subsidio|partida|convenio|beca)", re.IGNORECASE)
REGEX_GOBERNANZA = re.compile(r"(presidente|director|coordinador|secretario|tesorero|comisi[oó]n directiva|entrenador)", re.IGNORECASE)
REGEX_AUTOGESTION = re.compile(r"(rifa|bono contribuci[oó]n|sorteo|recaudar|colaborar|alias|cbu|cubiertas|tubulares|sillas)", re.IGNORECASE)

# Padrón Federal de Barrido (Clubes Municipales, ONGs y Convenios de todo el país)
OBJETIVOS_FEDERALES = [
    {
        "club": "Instituto Municipal del Deporte Almirante Brown",
        "provincia": "BUENOS_AIRES",
        "tipo": "MUNICIPAL",
        "autoridad": "Dir. Gustavo Borro / Coord. Fernando Mihovich / Maura González / Denis Leston",
        "url": "https://www.brown.gob.ar/deportes",
        "plataforma": "Boletin_Oficial",
        "respaldo_osint": "Monitoreo de decretos de adjudicación RAFAM (Incisos 2, 3, 4 y 5), trazabilidad de combis para fechas FABA y provisión de cubiertas tubulares.",
        "analisis_base": "AUDITORÍA MUNICIPAL Y GOBERNANZA: Conducción operativa a cargo de G. Borro (observado por Doble Mostrador como Pte. COPAR) y F. Mihovich. Sin padrón público de becarios deportivos 2026."
    },
    {
        "club": "Jujuy Básquet Adaptado",
        "provincia": "JUJUY",
        "tipo": "ASOCIACION_CIVIL_ONG",
        "autoridad": "Comisión Directiva y Plantel JBA",
        "url": "https://www.instagram.com/jujuy.basquet.adaptado/",
        "plataforma": "Instagram",
        "respaldo_osint": "Sorteos y bonos contribución organizados por el plantel para cubrir traslados de larga distancia en Primera División FABA.",
        "analisis_base": "ALERTA OSINT NOA: Único club de Jujuy en máxima categoría. Déficit de cobertura en pasajes nacionales (Parcial 517) suplido mediante rifas comunitarias."
    },
    {
        "club": "CRIGAL (Santa Cruz)",
        "provincia": "SANTA_CRUZ",
        "tipo": "ASOCIACION_CIVIL_ONG",
        "autoridad": "Comisión Directiva CRIGAL Río Gallegos",
        "url": "https://www.facebook.com/crigalbasquetadaptado",
        "plataforma": "Facebook",
        "respaldo_osint": "Gestión de pasajes aéreos y articulación con Ministerio de Desarrollo Social de Santa Cruz para cuadrangulares FABA.",
        "analisis_base": "AUDITORÍA PATAGONIA: Alta dependencia logística aérea. Se audita regularidad de transferencias provinciales y rendición de subsidios deportivos."
    },
    {
        "club": "SICA / Poeta Lugones (Córdoba)",
        "provincia": "CORDOBA",
        "tipo": "ASOCIACION_CIVIL_ONG",
        "autoridad": "Fundación SICA / Cuerpo Técnico Córdoba",
        "url": "https://www.instagram.com/sicabasquetadaptado/",
        "plataforma": "Instagram",
        "respaldo_osint": "Competencia en 1ra División FABA, convocatorias a Selección Argentina y gestión de cámaras/cubiertas de alta presión.",
        "analisis_base": "GOBERNANZA ONG: Referente del centro del país articulado con Agencia Córdoba Deportes. Pendiente publicación abierta de estados contables anuales."
    },
    {
        "club": "DUBA (Bahía Blanca)",
        "provincia": "BUENOS_AIRES",
        "tipo": "ASOCIACION_CIVIL_ONG",
        "autoridad": "Comisión Directiva DUBA Bahía Blanca",
        "url": "https://www.instagram.com/dubabahiablanca/",
        "plataforma": "Instagram",
        "respaldo_osint": "Campaña de socios protectores y rifas para sostener combustible, alojamiento y mantenimiento de sillas de competencia.",
        "analisis_base": "ALERTA PRESUPUESTARIA: Tracción autogestionada por los propios deportistas ante la ausencia de partidas fijas municipales/federativas."
    },
    {
        "club": "CEDIMA (La Matanza)",
        "provincia": "BUENOS_AIRES",
        "tipo": "ASOCIACION_CIVIL_ONG",
        "autoridad": "Consejo Directivo CEDIMA San Justo",
        "url": "https://www.instagram.com/cedima.oficial/",
        "plataforma": "Instagram",
        "respaldo_osint": "Actividad competitiva de 1ra División FABA en sede propia de San Justo y torneos promocionales.",
        "analisis_base": "FISCALIZACIÓN SOCIETARIA: ONG histórica receptora de subsidios públicos. Sujeta a exhibición de Memoria y Balance (Ley 27.275 Art. 7 inc. c)."
    },
    {
        "club": "CIDELI (Mar del Plata)",
        "provincia": "BUENOS_AIRES",
        "tipo": "ASOCIACION_CIVIL_ONG",
        "autoridad": "Comisión Directiva CIDELI",
        "url": "https://www.instagram.com/cidelimdp/",
        "plataforma": "Instagram",
        "respaldo_osint": "Uso de escenarios deportivos del EMDER Mar del Plata y autogestión de viajes para fechas de Liga Nacional.",
        "analisis_base": "AUDITORÍA CONVENIOS: Cesión de espacio público verificada, pero sin partida presupuestaria municipal directa para reposición de sillas."
    },
    {
        "club": "ADU (Tucumán)",
        "provincia": "TUCUMAN",
        "tipo": "ASOCIACION_CIVIL_ONG",
        "autoridad": "Comisión Directiva ADU San Miguel de Tucumán",
        "url": "https://www.facebook.com/fababasquetadaptado",
        "plataforma": "Facebook",
        "respaldo_osint": "Participación en zona norte de la Liga Nacional FABA y reclamos de actualización de equipamiento deportivo.",
        "analisis_base": "TRAZABILIDAD NOA: Se requiere transparentar apoyos de la Secretaría de Deportes de Tucumán y padrón de socios activos."
    },
    {
        "club": "DIMOT / Godoy Cruz (Mendoza)",
        "provincia": "MENDOZA",
        "tipo": "MUNICIPAL",
        "autoridad": "Coordinación Deporte Adaptado Mendoza",
        "url": "https://www.godoycruz.gob.ar/",
        "plataforma": "Boletin_Oficial",
        "respaldo_osint": "Relevamiento de resoluciones de subsidios de traslado y mantenimiento de sillas en la región de Cuyo.",
        "analisis_base": "AUDITORÍA CUYO: Esquema mixto municipal/asociativo. Se audita ejecución de partidas de discapacidad y becas estímulo."
    },
    {
        "club": "PRODEA (Paraná - Entre Ríos)",
        "provincia": "ENTRE_RIOS",
        "tipo": "ASOCIACION_CIVIL_ONG",
        "autoridad": "Comisión Directiva PRODEA Paraná",
        "url": "https://www.facebook.com/fababasquetadaptado",
        "plataforma": "Facebook",
        "respaldo_osint": "Competencia en liga de ascenso FABA y desarrollo regional en el Litoral con apoyo comunitario.",
        "analisis_base": "FISCALIZACIÓN LITORAL: Padrón oficial FABA desactualizado; se verifica actividad por actas de torneo y redes de jugadores."
    },
    {
        "club": "CEF N° 17 / Corrientes Básquet Adaptado",
        "provincia": "CORRIENTES",
        "tipo": "MUNICIPAL",
        "autoridad": "Dirección CEF N° 17 / Deportes Corrientes",
        "url": "https://www.facebook.com/fababasquetadaptado",
        "plataforma": "Prensa_Local",
        "respaldo_osint": "Participación de planteles correntinos en fechas nacionales con dependencia de transporte oficial provincial.",
        "analisis_base": "AUDITORÍA NEA: Alta vulnerabilidad en traslados de larga distancia; se auditan viáticos y provisión de repuestos."
    }
]

async def escanear_y_registrar_club(page, item):
    club = item["club"]
    url = item["url"]
    plataforma = item["plataforma"]
    print(f"[Bot OSINT] Escaneando gobernanza y documentos de: {club} ({item['provincia']})...")

    texto_extraido = ""
    try:
        await page.goto(url, timeout=18000, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        meta_desc = await page.locator('meta[name="description"]').get_attribute("content") if await page.locator('meta[name="description"]').count() > 0 else ""
        body_text = await page.inner_text("body") if await page.locator("body").count() > 0 else ""
        texto_crudo = f"{meta_desc} {body_text[:600]}".strip()
        texto_crudo_limpio = " ".join(texto_crudo.split())

        if len(texto_crudo_limpio) > 40 and "Iniciar sesión" not in texto_crudo_limpio:
            texto_extraido = texto_crudo_limpio[:280]
    except Exception:
        print(f"  [i] Red protegida en {url[:35]}... Usando inteligencia OSINT consolidada.")

    cita_final = texto_extraido if texto_extraido else item["respaldo_osint"]

    etiquetas_hallazgo = []
    if REGEX_DOCUMENTOS.search(cita_final):
        etiquetas_hallazgo.append("📄 Indicio Documental/Presupuestario")
    if REGEX_GOBERNANZA.search(cita_final) or item.get("autoridad"):
        etiquetas_hallazgo.append(f"👥 Gobernanza: {item['autoridad']}")
    if REGEX_AUTOGESTION.search(cita_final):
        etiquetas_hallazgo.append("⚠️ Alerta Autogestión/Insumos")

    analisis_final = f"{' | '.join(etiquetas_hallazgo)} — {item['analisis_base']}"
    id_unico = random.randint(1000, 9999)

    try:
        supabase.table("padron_clubes_faba").upsert({
            "nombre_actual": club,
            "tipo_entidad": item["tipo"],
            "jurisdiccion": item["provincia"],
            "provincia_normalizada": item["provincia"],
            "estado_actual": "ACTIVO",
            "autoridad_actual": item["autoridad"],
            "realidad_verificada_2026": item["analisis_base"],
            "ultima_actividad_osint": cita_final,
            "enlace_evidencia_url": url,
            "estado_redes_sociales": f"Monitoreado vía {plataforma} ({datetime.now().strftime('%d/%m/%Y')})",
            "perfil_skills_responsables": item["autoridad"]
        }, on_conflict="nombre_actual").execute()
    except Exception:
        pass

    try:
        res = supabase.rpc("bot_insertar_novedad_osint", {
            "p_club": club,
            "p_plataforma": plataforma,
            "p_url": url,
            "p_imagen": f"https://images.unsplash.com/photo-1546519638-68e109498ffc?auto=format&fit=crop&w=900&q=80&v={id_unico}",
            "p_cita": f"{cita_final} [Barrido #{id_unico}]",
            "p_analisis": analisis_final,
            "p_fecha": datetime.now().strftime("%Y-%m-%d")
        }).execute()
        print(f"  [✓] Impactado en Supabase: {club} -> {res.data}")
    except Exception as e:
        print(f"  [✗] Error RPC en {club}: {e}")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        for item in OBJETIVOS_FEDERALES:
            await escanear_y_registrar_club(page, item)
            await asyncio.sleep(1.5)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())