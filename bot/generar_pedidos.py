"""Deja en la cola de revisión un BORRADOR de pedido de acceso a la información por cada jurisdicción que
no publica datos abiertos o publica a medias (según datos/transparencia.json). No envía nada: el pedido lo
presenta una persona, con su nombre. Un borrador por jurisdicción y por mes. Uso: python generar_pedidos.py"""
import hashlib
import json
import os
from datetime import datetime, timezone

import orquestador_bots_audita as o

AGENTE = "generador_pedidos"
AQUI = os.path.dirname(os.path.abspath(__file__))
ITEMS = ["Partidas presupuestarias vigentes y su ejecución (crédito, compromiso, devengado y pagado) destinadas a deporte "
         "y, en particular, a deporte adaptado o para personas con discapacidad, de los últimos tres ejercicios",
         "Subsidios, becas, aportes o convenios otorgados a clubes, asociaciones o deportistas de básquet sobre silla de ruedas, "
         "con el acto administrativo que los aprobó (número, fecha) y su rendición de cuentas",
         "Compras o contrataciones de sillas deportivas, repuestos, traslados o alojamiento para competencias, con su expediente",
         "Enlace o canal oficial donde se publica el Boletín Oficial y el procedimiento para pedir información pública"]


BASE_CARTA = ("la Constitución Nacional (arts. 1, 14, 33 y 75 inc. 22), el art. 13 de la Convención Americana sobre Derechos "
              "Humanos y la jurisprudencia de la Corte Suprema de Justicia de la Nación (caso \"CIPPEC\", 2014)")


def texto_pedido(j: dict) -> str:
    """En la carta va la base constitucional y la norma que obliga A ESE organismo: a un municipio no se le cita
    la ley provincial (en la Provincia de Buenos Aires, la 12.475 solo alcanza al Ejecutivo provincial)."""
    p = j["pedido"]
    if j.get("tipo", "municipio") == "municipio":
        base = BASE_CARTA + (f", y por la {p['norma']}" if p.get("ordenanza") else
                             ", y por la ordenanza municipal de acceso a la información pública que corresponda")
    else:
        base = BASE_CARTA + ("" if p["norma"].startswith("sin ley") else f", y por la {p['norma']}")
    prov = ""
    items = "\n".join(f"  {i}. {t}" for i, t in enumerate(ITEMS, 1))
    return (f"Asunto: Solicitud de acceso a la información pública\n\nA: {j['nombre']}\n\n"
            f"Por la presente, en ejercicio del derecho de acceso a la información pública garantizado por {base}{prov}, "
            f"solicito se me brinde la siguiente información, preferentemente en formato digital abierto:\n\n{items}\n\n"
            f"Solicito respuesta dentro del plazo previsto: {p['plazo']}.\n\n"
            "No se requiere información personal sensible de terceros; si algún dato debiera reservarse, solicito que se entregue "
            "el resto con la parte reservada tachada y se indique el fundamento.\n\n"
            "Datos del solicitante:\nNombre: [Nombre y apellido]\nDNI: [DNI]\nCorreo para la respuesta: [Correo]\n")


def retirar_versiones_viejas(inst_id, hash_nuevo):
    """Si el texto del borrador cambió (p. ej. se corrigió), se retira el pendiente anterior para no duplicar."""
    pend = o.db().table("cola_revision").select("id,hash_sha256").eq("agente", AGENTE).eq("estado", "pendiente") \
        .eq("institucion_id", inst_id).execute().data or []
    for p in pend:
        if p.get("hash_sha256") != hash_nuevo:
            o.db().table("cola_revision").update({"estado": "rechazada", "motivo_codigo": "otro", "revisada_por": f"{AGENTE} (automático)",
                                                  "revisada_en": o.ahora().isoformat(),
                                                  "nota_revision": "Reemplazado por una versión corregida del borrador."}).eq("id", p["id"]).execute()


def main():
    datos = json.load(open(os.path.join(AQUI, "..", "datos", "transparencia.json"), encoding="utf-8"))
    insts = {i["slug"]: i["id"] for i in o.db().table("instituciones").select("id,slug").execute().data or []}
    mes = datetime.now(timezone.utc).strftime("%Y-%m")
    n = {"nuevo": 0, "duplicado": 0, "otro": 0}
    for j in datos["jurisdicciones"]:
        if j["estado"] == "publica" or j["slug"] not in insts:
            continue
        texto = texto_pedido(j)
        cuerpo = json.dumps({"slug": j["slug"], "mes": mes, "texto": texto}, ensure_ascii=False).encode()
        url = (j.get("sitio_web") or "https://auditadeporte.vercel.app/").rstrip("/") + f"/#pedido-{mes}"
        cap = o.Captura(url, 200, cuerpo, hashlib.sha256(cuerpo).hexdigest())
        retirar_versiones_viejas(insts[j["slug"]], cap.sha256)
        r = o.proponer(AGENTE, "propuesta_cambio", f"Borrador de pedido de acceso: {j['nombre']} ({'no publica datos abiertos' if j['estado'] == 'no_publica' else 'publica a medias'})",
                       cap, None, insts[j["slug"]],
                       {"accion": "solo_informativa", "fuente": "generador_pedidos",
                        "parametros": {"texto_pedido": texto, "motivo": j["motivo"], "norma": j["pedido"]["norma"],
                                       "plazo": j["pedido"]["plazo"], "reclamo": j["pedido"]["reclamo"], "sitio_oficial": j.get("sitio_web"),
                                       "nota": "Revisá el texto, completá tus datos y presentalo por el canal oficial. Guardá el número de expediente."}},
                       texto_para_filtro=j["nombre"])
        n[r if r in n else "otro"] += 1
    print(f"borradores: {n}")


if __name__ == "__main__":
    main()
