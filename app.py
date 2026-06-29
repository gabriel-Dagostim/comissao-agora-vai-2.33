import logging
import os
import re
import time
import unicodedata
from pathlib import Path

import pandas as pd
from flask import Flask, render_template, request, flash
from waitress import serve
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

# Conexão com SQL Server para consulta de comissão
try:
    import pyodbc
except Exception:
    pyodbc = None

# ============================
# Configuração básica
# ============================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"

for d in (DATA_DIR, STATIC_DIR):
    d.mkdir(exist_ok=True, parents=True)

APP_TITLE = "Consulta de Comissão"
APP_BRAND = "SIT Estrela"
APP_BRAND_SUB = "Setor de Inovação e Tecnologia"
CONSULT_COOLDOWN_SEC = 4
_last_consult_by_ip: dict[str, float] = {}

app = Flask(__name__)
app.config["DEBUG"] = False
app.config["TESTING"] = False
app.config["PROPAGATE_EXCEPTIONS"] = False
app.secret_key = os.getenv("FLASK_SECRET_KEY", "segredo-simples")


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response

# ============================
# Configuração de Banco (SQL Server)
# ============================
DB_DRIVER   = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
DB_SERVER   = os.getenv("DB_SERVER", "")
DB_DATABASE = os.getenv("DB_DATABASE", "")
DB_USER     = os.getenv("DB_USER", "")
DB_PASS     = os.getenv("DB_PASS", "")
DB_TRUSTED  = os.getenv("DB_TRUSTED", "0")  # 1 para Trusted_Connection


def db_ready() -> bool:
    if pyodbc is None:
        return False
    if DB_TRUSTED == "1":
        return bool(DB_SERVER and DB_DATABASE)
    return bool(DB_SERVER and DB_DATABASE and DB_USER and DB_PASS)


def get_conn():
    if not db_ready():
        raise RuntimeError(
            "Banco não configurado. Defina DB_SERVER/DB_DATABASE e (DB_USER/DB_PASS) ou DB_TRUSTED=1."
        )
    if DB_TRUSTED == "1":
        conn_str = f"DRIVER={{{DB_DRIVER}}};SERVER={DB_SERVER};DATABASE={DB_DATABASE};Trusted_Connection=yes;"
    else:
        conn_str = f"DRIVER={{{DB_DRIVER}}};SERVER={DB_SERVER};DATABASE={DB_DATABASE};UID={DB_USER};PWD={DB_PASS};"
    return pyodbc.connect(conn_str, timeout=30)


def _placeholders(n: int) -> str:
    return ",".join(["?"] * n) if n > 0 else ""


# ============================
# Utilitários
# ============================
def strip_accents(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm_text(s: str) -> str:
    return strip_accents(str(s)).strip().lower()


def only_digits(s: str) -> str:
    return re.sub(r"\D+", "", str(s or ""))


# ============================
# Consulta SQL (modo banco)
# ============================
def consultar_comissao_db(
    filial: int,
    cargos: list[int],
    codproduto: str | None = None,
    ean: str | None = None,
) -> tuple[dict, pd.DataFrame]:
    """
    Retorna:
      produto_info (dict) e df_result (1 linha por cargo)
    """

    codproduto = only_digits(codproduto or "")
    ean = only_digits(ean or "")

    if not codproduto and not ean:
        raise ValueError("Informe EAN ou Código Interno.")

    cargos = [int(x) for x in cargos if str(x).strip() != ""]
    if not cargos:
        raise ValueError("Informe ao menos 1 cargo.")

    cargo_in = _placeholders(len(cargos))

    # filtro produto
    if codproduto:
        filtro_prod = "AND p.cd_prod = ?"
        prod_param = int(codproduto)
        ean_select = "MIN(b.cd_barra) AS ean"
        join_barra = """
LEFT JOIN est_prod_cd_barra b
  ON b.cd_emp  = p.cd_emp
 AND b.cd_prod = p.cd_prod
"""
        ean_params = []
    else:
        filtro_prod = """
AND EXISTS (
    SELECT 1
    FROM est_prod_cd_barra b2
    WHERE b2.cd_emp = p.cd_emp
      AND b2.cd_prod = p.cd_prod
      AND b2.cd_barra = ?
)
"""
        prod_param = ean
        ean_select = "? AS ean"
        join_barra = ""
        ean_params = [ean]

    # ============================
    # SQL principal: agora enriquecendo pela VIEW
    # ============================
    sql_enriquecido = f"""
WITH prod AS (
    SELECT
        p.cd_emp,
        c.cd_filial,
        p.cd_prod,
        p.ds_prod,
        p.cd_fabric,
        am.cd_arv_merc_familia,
        am.cd_mc,
        am.cd_arv_merc_categ,
        am.cd_arv_merc_linha,

        v.NM_FABRIC           AS fabricante,
        NULL                  AS marca,
        v.DS_ARV_MERC_FAMILIA AS familia,
        v.DS_ARV_MERC_CATEG   AS categoria,
        v.DS_ARV_MERC_LINHA   AS linha,

        {ean_select}
    FROM est_prod_cpl c
    JOIN est_prod p
      ON p.cd_emp  = c.cd_emp
     AND p.cd_prod = c.cd_prod

    LEFT JOIN EST_PROD_EST_ARV_MERCADOLOGICA am
      ON am.cd_emp  = p.cd_emp
     AND am.cd_prod = p.cd_prod

    LEFT JOIN V_EST_PROD_ARV_MERCADOLOGICA v
      ON v.cd_emp  = p.cd_emp
     AND v.cd_prod = p.cd_prod

    {join_barra}

    WHERE c.cd_filial = ?
      AND p.sts_prod IN (0,2)
      {filtro_prod}

    GROUP BY
        p.cd_emp, c.cd_filial, p.cd_prod, p.ds_prod, p.cd_fabric,
        am.cd_arv_merc_familia, am.cd_mc, am.cd_arv_merc_categ, am.cd_arv_merc_linha,
        v.NM_FABRIC, v.DS_ARV_MERC_FAMILIA, v.DS_ARV_MERC_CATEG, v.DS_ARV_MERC_LINHA
),

cargo_tbl AS (
    SELECT DISTINCT
        x.cd_emp,
        x.cd_cargo,
        x.cd_tbl_comis
    FROM v_fp_cargo_est_prod_tbl_comis_tentacle x
    WHERE x.cd_grp_econ = 1
      AND x.cd_cargo IN ({cargo_in})
),

regras AS (
    -- 1) PRODUTO
    SELECT pr.cd_emp, pr.cd_filial, pr.cd_prod, pr.ds_prod, pr.ean,
           pr.fabricante, pr.marca, pr.familia, pr.categoria, pr.linha,
           ct.cd_cargo, ct.cd_tbl_comis,
           1 AS prioridade, 'PRODUTO' AS nivel,
           a.perc_comis
    FROM prod pr
    JOIN cargo_tbl ct ON ct.cd_emp = pr.cd_emp
    JOIN EST_PROD_TBL_COMIS_EST_PROD a
      ON a.cd_emp       = pr.cd_emp
     AND a.cd_tbl_comis = ct.cd_tbl_comis
     AND a.cd_prod      = pr.cd_prod

    UNION ALL

    -- 2) FAMÍLIA
    SELECT pr.cd_emp, pr.cd_filial, pr.cd_prod, pr.ds_prod, pr.ean,
           pr.fabricante, pr.marca, pr.familia, pr.categoria, pr.linha,
           ct.cd_cargo, ct.cd_tbl_comis,
           2, 'FAMILIA',
           a.perc_comis
    FROM prod pr
    JOIN cargo_tbl ct ON ct.cd_emp = pr.cd_emp
    JOIN EST_PROD_TBL_COMIS_EST_ARV_MERC_FAMILIA a
      ON a.cd_emp       = pr.cd_emp
     AND a.cd_tbl_comis = ct.cd_tbl_comis
     AND a.cd_arv_merc_familia = pr.cd_arv_merc_familia
    WHERE pr.cd_arv_merc_familia IS NOT NULL

    UNION ALL

    -- 3) MARCA
    SELECT pr.cd_emp, pr.cd_filial, pr.cd_prod, pr.ds_prod, pr.ean,
           pr.fabricante, pr.marca, pr.familia, pr.categoria, pr.linha,
           ct.cd_cargo, ct.cd_tbl_comis,
           3, 'MARCA',
           a.perc_comis
    FROM prod pr
    JOIN cargo_tbl ct ON ct.cd_emp = pr.cd_emp
    JOIN EST_PROD_TBL_COMIS_EST_MC a
      ON a.cd_emp       = pr.cd_emp
     AND a.cd_tbl_comis = ct.cd_tbl_comis
     AND a.cd_mc        = pr.cd_mc
    WHERE pr.cd_mc IS NOT NULL

    UNION ALL

    -- 4) FABRICANTE
    SELECT pr.cd_emp, pr.cd_filial, pr.cd_prod, pr.ds_prod, pr.ean,
           pr.fabricante, pr.marca, pr.familia, pr.categoria, pr.linha,
           ct.cd_cargo, ct.cd_tbl_comis,
           4, 'FABRICANTE',
           a.perc_comis
    FROM prod pr
    JOIN cargo_tbl ct ON ct.cd_emp = pr.cd_emp
    JOIN EST_PROD_TBL_COMIS_EST_PROD_FABRIC a
      ON a.cd_emp       = pr.cd_emp
     AND a.cd_tbl_comis = ct.cd_tbl_comis
     AND a.cd_fabric    = pr.cd_fabric
    WHERE pr.cd_fabric IS NOT NULL

    UNION ALL

    -- 5) CATEGORIA
    SELECT pr.cd_emp, pr.cd_filial, pr.cd_prod, pr.ds_prod, pr.ean,
           pr.fabricante, pr.marca, pr.familia, pr.categoria, pr.linha,
           ct.cd_cargo, ct.cd_tbl_comis,
           5, 'CATEGORIA',
           a.perc_comis
    FROM prod pr
    JOIN cargo_tbl ct ON ct.cd_emp = pr.cd_emp
    JOIN EST_PROD_TBL_COMIS_EST_ARV_MERC_CATEGORIA a
      ON a.cd_emp       = pr.cd_emp
     AND a.cd_tbl_comis = ct.cd_tbl_comis
     AND a.cd_arv_merc_categ = pr.cd_arv_merc_categ
    WHERE pr.cd_arv_merc_categ IS NOT NULL

    UNION ALL

    -- 6) LINHA
    SELECT pr.cd_emp, pr.cd_filial, pr.cd_prod, pr.ds_prod, pr.ean,
           pr.fabricante, pr.marca, pr.familia, pr.categoria, pr.linha,
           ct.cd_cargo, ct.cd_tbl_comis,
           6, 'LINHA',
           a.perc_comis
    FROM prod pr
    JOIN cargo_tbl ct ON ct.cd_emp = pr.cd_emp
    JOIN EST_PROD_TBL_COMIS_EST_ARV_MERC_LINHA a
      ON a.cd_emp       = pr.cd_emp
     AND a.cd_tbl_comis = ct.cd_tbl_comis
     AND a.cd_arv_merc_linha = pr.cd_arv_merc_linha
    WHERE pr.cd_arv_merc_linha IS NOT NULL

    UNION ALL

    -- 7) FILIAL
    SELECT pr.cd_emp, pr.cd_filial, pr.cd_prod, pr.ds_prod, pr.ean,
           pr.fabricante, pr.marca, pr.familia, pr.categoria, pr.linha,
           ct.cd_cargo, ct.cd_tbl_comis,
           7, 'FILIAL',
           a.perc_comis
    FROM prod pr
    JOIN cargo_tbl ct ON ct.cd_emp = pr.cd_emp
    JOIN EST_PROD_TBL_COMIS_PRC_FILIAL a
      ON a.cd_emp       = pr.cd_emp
     AND a.cd_tbl_comis = ct.cd_tbl_comis
     AND a.cd_filial    = pr.cd_filial
),

final AS (
    SELECT
        r.*,
        ROW_NUMBER() OVER (
            PARTITION BY r.cd_cargo, r.cd_prod
            ORDER BY r.prioridade
        ) AS rn
    FROM regras r
)

SELECT
    f.cd_cargo,
    cg.ds_cargo AS nome_cargo,
    f.cd_prod,
    f.ds_prod,
    f.ean,
    f.fabricante,
    f.marca,
    f.familia,
    f.categoria,
    f.linha,
    f.perc_comis AS perc_comissao_final,
    f.nivel      AS nivel_aplicado
FROM final f
LEFT JOIN fp_cargo cg
  ON cg.cd_emp = f.cd_emp
 AND cg.cd_cargo = f.cd_cargo
WHERE f.rn = 1
ORDER BY f.cd_cargo, f.cd_prod;
"""

    params = []
    params.extend(ean_params)          # se ean_select usa "?" vem primeiro
    params.append(int(filial))         # filial
    params.append(prod_param)          # cd_prod OU ean do exists
    params.extend(cargos)              # IN cargos

    with get_conn() as cn:
        try:
            df = pd.read_sql(sql_enriquecido, cn, params=params)
        except Exception:
            # fallback: mantém cargos e produto, e também usa a VIEW para descritivos
            sql_safe = f"""
WITH prod AS (
    SELECT
        p.cd_emp,
        c.cd_filial,
        p.cd_prod,
        p.ds_prod,
        p.cd_fabric,
        am.cd_arv_merc_familia,
        am.cd_mc,
        am.cd_arv_merc_categ,
        am.cd_arv_merc_linha,

        v.NM_FABRIC           AS fabricante,
        NULL                  AS marca,
        v.DS_ARV_MERC_FAMILIA AS familia,
        v.DS_ARV_MERC_CATEG   AS categoria,
        v.DS_ARV_MERC_LINHA   AS linha,

        {ean_select}
    FROM est_prod_cpl c
    JOIN est_prod p
      ON p.cd_emp  = c.cd_emp
     AND p.cd_prod = c.cd_prod
    LEFT JOIN EST_PROD_EST_ARV_MERCADOLOGICA am
      ON am.cd_emp  = p.cd_emp
     AND am.cd_prod = p.cd_prod

    LEFT JOIN V_EST_PROD_ARV_MERCADOLOGICA v
      ON v.cd_emp  = p.cd_emp
     AND v.cd_prod = p.cd_prod

    {join_barra}

    WHERE c.cd_filial = ?
      AND p.sts_prod IN (0,2)
      {filtro_prod}

    GROUP BY
        p.cd_emp, c.cd_filial, p.cd_prod, p.ds_prod, p.cd_fabric,
        am.cd_arv_merc_familia, am.cd_mc, am.cd_arv_merc_categ, am.cd_arv_merc_linha,
        v.NM_FABRIC, v.DS_ARV_MERC_FAMILIA, v.DS_ARV_MERC_CATEG, v.DS_ARV_MERC_LINHA
),

cargo_tbl AS (
    SELECT DISTINCT
        x.cd_emp,
        x.cd_cargo,
        x.cd_tbl_comis
    FROM v_fp_cargo_est_prod_tbl_comis_tentacle x
    WHERE x.cd_grp_econ = 1
      AND x.cd_cargo IN ({cargo_in})
),

regras AS (
    SELECT pr.cd_emp, pr.cd_filial, pr.cd_prod, pr.ds_prod, pr.ean,
           pr.fabricante, pr.marca, pr.familia, pr.categoria, pr.linha,
           ct.cd_cargo, ct.cd_tbl_comis,
           1 AS prioridade, 'PRODUTO' AS nivel,
           a.perc_comis
    FROM prod pr
    JOIN cargo_tbl ct ON ct.cd_emp = pr.cd_emp
    JOIN EST_PROD_TBL_COMIS_EST_PROD a
      ON a.cd_emp       = pr.cd_emp
     AND a.cd_tbl_comis = ct.cd_tbl_comis
     AND a.cd_prod      = pr.cd_prod

    UNION ALL

    SELECT pr.cd_emp, pr.cd_filial, pr.cd_prod, pr.ds_prod, pr.ean,
           pr.fabricante, pr.marca, pr.familia, pr.categoria, pr.linha,
           ct.cd_cargo, ct.cd_tbl_comis,
           2, 'FAMILIA',
           a.perc_comis
    FROM prod pr
    JOIN cargo_tbl ct ON ct.cd_emp = pr.cd_emp
    JOIN EST_PROD_TBL_COMIS_EST_ARV_MERC_FAMILIA a
      ON a.cd_emp       = pr.cd_emp
     AND a.cd_tbl_comis = ct.cd_tbl_comis
     AND a.cd_arv_merc_familia = pr.cd_arv_merc_familia
    WHERE pr.cd_arv_merc_familia IS NOT NULL

    UNION ALL

    SELECT pr.cd_emp, pr.cd_filial, pr.cd_prod, pr.ds_prod, pr.ean,
           pr.fabricante, pr.marca, pr.familia, pr.categoria, pr.linha,
           ct.cd_cargo, ct.cd_tbl_comis,
           3, 'MARCA',
           a.perc_comis
    FROM prod pr
    JOIN cargo_tbl ct ON ct.cd_emp = pr.cd_emp
    JOIN EST_PROD_TBL_COMIS_EST_MC a
      ON a.cd_emp       = pr.cd_emp
     AND a.cd_tbl_comis = ct.cd_tbl_comis
     AND a.cd_mc        = pr.cd_mc
    WHERE pr.cd_mc IS NOT NULL

    UNION ALL

    SELECT pr.cd_emp, pr.cd_filial, pr.cd_prod, pr.ds_prod, pr.ean,
           pr.fabricante, pr.marca, pr.familia, pr.categoria, pr.linha,
           ct.cd_cargo, ct.cd_tbl_comis,
           4, 'FABRICANTE',
           a.perc_comis
    FROM prod pr
    JOIN cargo_tbl ct ON ct.cd_emp = pr.cd_emp
    JOIN EST_PROD_TBL_COMIS_EST_PROD_FABRIC a
      ON a.cd_emp       = pr.cd_emp
     AND a.cd_tbl_comis = ct.cd_tbl_comis
     AND a.cd_fabric    = pr.cd_fabric
    WHERE pr.cd_fabric IS NOT NULL

    UNION ALL

    SELECT pr.cd_emp, pr.cd_filial, pr.cd_prod, pr.ds_prod, pr.ean,
           pr.fabricante, pr.marca, pr.familia, pr.categoria, pr.linha,
           ct.cd_cargo, ct.cd_tbl_comis,
           5, 'CATEGORIA',
           a.perc_comis
    FROM prod pr
    JOIN cargo_tbl ct ON ct.cd_emp = pr.cd_emp
    JOIN EST_PROD_TBL_COMIS_EST_ARV_MERC_CATEGORIA a
      ON a.cd_emp       = pr.cd_emp
     AND a.cd_tbl_comis = ct.cd_tbl_comis
     AND a.cd_arv_merc_categ = pr.cd_arv_merc_categ
    WHERE pr.cd_arv_merc_categ IS NOT NULL

    UNION ALL

    SELECT pr.cd_emp, pr.cd_filial, pr.cd_prod, pr.ds_prod, pr.ean,
           pr.fabricante, pr.marca, pr.familia, pr.categoria, pr.linha,
           ct.cd_cargo, ct.cd_tbl_comis,
           6, 'LINHA',
           a.perc_comis
    FROM prod pr
    JOIN cargo_tbl ct ON ct.cd_emp = pr.cd_emp
    JOIN EST_PROD_TBL_COMIS_EST_ARV_MERC_LINHA a
      ON a.cd_emp       = pr.cd_emp
     AND a.cd_tbl_comis = ct.cd_tbl_comis
     AND a.cd_arv_merc_linha = pr.cd_arv_merc_linha
    WHERE pr.cd_arv_merc_linha IS NOT NULL

    UNION ALL

    SELECT pr.cd_emp, pr.cd_filial, pr.cd_prod, pr.ds_prod, pr.ean,
           pr.fabricante, pr.marca, pr.familia, pr.categoria, pr.linha,
           ct.cd_cargo, ct.cd_tbl_comis,
           7, 'FILIAL',
           a.perc_comis
    FROM prod pr
    JOIN cargo_tbl ct ON ct.cd_emp = pr.cd_emp
    JOIN EST_PROD_TBL_COMIS_PRC_FILIAL a
      ON a.cd_emp       = pr.cd_emp
     AND a.cd_tbl_comis = ct.cd_tbl_comis
     AND a.cd_filial    = pr.cd_filial
),

final AS (
    SELECT
        r.*,
        ROW_NUMBER() OVER (
            PARTITION BY r.cd_cargo, r.cd_prod
            ORDER BY r.prioridade
        ) AS rn
    FROM regras r
)
SELECT
    f.cd_cargo,
    cg.ds_cargo AS nome_cargo,
    f.cd_prod,
    f.ds_prod,
    f.ean,
    f.fabricante,
    f.marca,
    f.familia,
    f.categoria,
    f.linha,
    f.perc_comis AS perc_comissao_final,
    f.nivel      AS nivel_aplicado
FROM final f
LEFT JOIN fp_cargo cg
  ON cg.cd_emp = f.cd_emp
 AND cg.cd_cargo = f.cd_cargo
WHERE f.rn = 1
ORDER BY f.cd_cargo, f.cd_prod;
"""
            df = pd.read_sql(sql_safe, cn, params=params)

    if df.empty:
        return {}, df

    first = df.iloc[0]
    produto_info = {
        "ean": str(first.get("ean") or ""),
        "codproduto": str(first.get("cd_prod") or ""),
        "descricao": str(first.get("ds_prod") or ""),
        "fabricante": str(first.get("fabricante") or ""),
        "marca": str(first.get("marca") or ""),
        "familia": str(first.get("familia") or ""),
        "categoria": str(first.get("categoria") or ""),
        "linha": str(first.get("linha") or ""),
    }
    return produto_info, df


def _client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _consult_cooldown_remaining(ip: str) -> float:
    last = _last_consult_by_ip.get(ip, 0.0)
    return max(0.0, CONSULT_COOLDOWN_SEC - (time.time() - last))


def _register_consult(ip: str) -> None:
    _last_consult_by_ip[ip] = time.time()


# ============================
# Rotas
# ============================
@app.route("/")
def index():
    use_db = db_ready()

    default_filial = int(os.getenv("DEFAULT_FILIAL", "1"))
    default_cargos = os.getenv("DEFAULT_CARGOS", "1,5,7,22,23,28,31,32")

    filial = request.args.get("filial", str(default_filial))
    cargos_raw = request.args.get("cargos", default_cargos)
    ean = request.args.get("ean", "")
    cod = request.args.get("codproduto", "")

    produto_info = None
    resultados = None

    if use_db and (only_digits(ean) or only_digits(cod)):
        client_ip = _client_ip()
        cooldown_left = _consult_cooldown_remaining(client_ip)
        if cooldown_left > 0:
            flash(
                f"Aguarde {int(cooldown_left + 0.99)} segundos antes de consultar novamente.",
                "warning",
            )
        else:
            _register_consult(client_ip)
            try:
                filial_i = int(only_digits(filial) or default_filial)
                cargos = [int(x) for x in re.findall(r"\d+", cargos_raw)] if cargos_raw else [1, 5, 7, 22, 23, 28, 31, 32]

                produto_info, df = consultar_comissao_db(
                    filial=filial_i,
                    cargos=cargos,
                    codproduto=cod or None,
                    ean=ean or None,
                )

                if df.empty:
                    flash("Produto não encontrado (ou sem regra para os cargos informados).", "warning")
                else:
                    resultados = []
                    for _, r in df.iterrows():
                        resultados.append({
                            "cargo": str(r.get("nome_cargo") or f"Cargo {int(r['cd_cargo'])}"),
                            "cd_cargo": int(r["cd_cargo"]),
                            "perc": float(r["perc_comissao_final"]) if pd.notna(r["perc_comissao_final"]) else None,
                            "nivel": str(r.get("nivel_aplicado") or "—"),
                        })

            except Exception:
                logger.exception("Falha na consulta de comissão")
                flash(
                    "Não foi possível concluir a consulta. Tente novamente ou contate o suporte.",
                    "danger",
                )

    return render_template(
        "index.html",
        app_title=APP_TITLE,
        app_brand=APP_BRAND,
        app_brand_sub=APP_BRAND_SUB,
        use_db=use_db,
        default_filial=default_filial,
        default_cargos=default_cargos,
        filial_val=filial,
        cargos_val=cargos_raw,
        ean_val=ean,
        cod_val=cod,
        produto_info=produto_info,
        resultados=resultados,
    )


@app.route("/health")
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    print(f"\n[INFO] Acesse em http://localhost:{port} ou http://<IP-da-sua-máquina>:{port}\n")
    serve(app, host=host, port=port)
