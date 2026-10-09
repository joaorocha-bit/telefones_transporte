import streamlit as st
import qrcode
import pandas as pd
from datetime import datetime, timezone, timedelta
import io
import hmac
import hashlib
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# CONFIGURAÇÃO E SEGURANÇA
# ==========================================
st.set_page_config(page_title="Controle de Telefones", page_icon="📱", layout="centered")

APP_URL = st.secrets.get("APP_URL", "https://telefonestransporte-ndzmusne7o33caaqh6tcwz.streamlit.app/")
SECRET_KEY = st.secrets.get("SECRET_KEY", "chave_secreta_super_segura_123")
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "admin123")
TEMPO_EXPIRACAO_MINUTOS = 3 

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Inicializa a sessão administrativa caso não exista
if "admin_autenticado" not in st.session_state:
    st.session_state["admin_autenticado"] = False

# ==========================================
# FUNÇÕES DE AUTENTICAÇÃO E GOOGLE SHEETS
# ==========================================
@st.cache_resource
def conectar_google_sheets():
    try:
        credentials_dict = dict(st.secrets["gcp_service_account"])
        credentials = Credentials.from_service_account_info(credentials_dict, scopes=SCOPES)
        return gspread.authorize(credentials)
    except Exception as e:
        st.error(f"Erro ao conectar com Google Sheets: {e}")
        return None

def obter_aba_planilha(nome_aba: str):
    client = conectar_google_sheets()
    if client:
        sheet_id = st.secrets["SPREADSHEET_ID"]
        return client.open_by_key(sheet_id).worksheet(nome_aba)
    return None

def carregar_base_colaboradores() -> dict:
    try:
        sheet = obter_aba_planilha("Colaboradores")
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        df["Matricula"] = df["Matricula"].astype(str).str.strip()
        return dict(zip(df["Matricula"], df["Nome"]))
    except Exception as e:
        st.error(f"Erro ao carregar colaboradores: {e}")
        return {}

def registrar_movimentacao(matricula: str, nome: str, telefone_id: str, acao: str):
    sheet = obter_aba_planilha("Historico")
    fuso_br = timezone(timedelta(hours=-3))
    timestamp_atual = datetime.now(fuso_br).strftime("%d/%m/%Y %H:%M:%S")
    nova_linha = [timestamp_atual, matricula, nome, telefone_id, acao]
    sheet.append_row(nova_linha)

# ==========================================
# FUNÇÕES DE VALIDAÇÃO DO QR CODE
# ==========================================
def gerar_assinatura(timestamp_str: str) -> str:
    return hmac.new(
        SECRET_KEY.encode(),
        timestamp_str.encode(),
        hashlib.sha256
    ).hexdigest()[:10]

def validar_token(t_param: str, s_param: str) -> tuple[bool, str]:
    if not t_param or not s_param:
        return False, "⚠️ Acesso negado. Escaneie o QR Code na base física para acessar o formulário."
    
    assinatura_esperada = gerar_assinatura(t_param)
    if not hmac.compare_digest(assinatura_esperada, s_param):
        return False, "❌ Assinatura do QR Code inválida."
    
    try:
        timestamp_qr = int(t_param)
        agora = int(datetime.now(timezone.utc).timestamp())
        diferenca_segundos = agora - timestamp_qr
        
        if diferenca_segundos < 0:
            return False, "Erro de fuso horário no servidor."
        
        if diferenca_segundos > (TEMPO_EXPIRACAO_MINUTOS * 60):
            return False, "⌛ Este QR Code expirou! Escaneie o QR Code atualizado na tela da base."
            
    except ValueError:
        return False, "Parâmetro de tempo em formato incorreto."
        
    return True, "Token Válido"

def gerar_imagem_qr(url_base: str) -> bytes:
    url_base = url_base.rstrip('/')
    timestamp_str = str(int(datetime.now(timezone.utc).timestamp()))
    assinatura = gerar_assinatura(timestamp_str)
    
    url_com_token = f"{url_base}?t={timestamp_str}&s={assinatura}"
    
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url_com_token)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="#1E1E1E", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

# ==========================================
# FRAGMENTO DE AUTO-REFRESH DO QR CODE
# ==========================================
@st.fragment(run_every="60s")
def renderizar_qr_code_auto():
    """Esta função roda sozinha a cada 60 segundos no navegador sem recarregar a página toda."""
    qr_bytes = gerar_imagem_qr(APP_URL)
    
    col1, col2 = st.columns([2, 1])
    with col1:
        st.image(qr_bytes, caption=f"Válido por {TEMPO_EXPIRACAO_MINUTOS} minutos.", width=340)
    with col2:
        st.markdown("### Instruções:")
        st.write("1. Abra a câmera do celular.")
        st.write("2. Escaneie o QR Code.")
        st.write("3. Preencha o formulário para retirar ou devolver.")

# ==========================================
# INTERFACE DO APP
# ==========================================
def main():
    st.title("📱 Gestão de Telefones")
    
    aba_usuario, aba_admin = st.tabs(["Formulário de Operação", "Painel Físico / Gerador"])

    # ----------------------------------------------------
    # ABA 1: FORMULÁRIO DO COLABORADOR
    # ----------------------------------------------------
    with aba_usuario:
        params = st.query_params
        t_param = params.get("t")
        s_param = params.get("s")
        
        token_valido, mensagem_erro = validar_token(t_param, s_param)
        
        if not token_valido:
            st.error(mensagem_erro)
        else:
            st.success("🔒 Acesso validado presencialmente.")
            st.markdown("---")
            
            base_colaboradores = carregar_base_colaboradores()
            
            with st.form("form_registro"):
                tipo_acao = st.radio("Selecione a ação:", ["Retirada", "Devolução"], horizontal=True)
                matricula = st.text_input("Matrícula do Colaborador").strip()
                codigo_tel = st.text_input("Código do Telefone (ex: TEL-01)").strip().upper()
                
                submit = st.form_submit_button("Confirmar Operação", type="primary")
                
                if submit:
                    re_valido, re_msg = validar_token(t_param, s_param)
                    
                    if not re_valido:
                        st.error("⏱️ O tempo do QR Code expirou enquanto você preenchia. Escaneie novamente na base.")
                    elif not matricula or not codigo_tel:
                        st.warning("⚠️ Preencha a Matrícula e o Código do Telefone.")
                    elif matricula not in base_colaboradores:
                        st.error(f"❌ Matrícula '{matricula}' não encontrada. Verifique com a supervisão.")
                    else:
                        nome_colaborador = base_colaboradores[matricula]
                        registrar_movimentacao(matricula, nome_colaborador, codigo_tel, tipo_acao)
                        
                        st.query_params.clear()
                        
                        st.balloons()
                        st.success(f"✅ **{tipo_acao}** registrada com sucesso!\n- **Colaborador:** {nome_colaborador}\n- **Aparelho:** {codigo_tel}")
                        st.info("Para registrar outro aparelho, escaneie novamente o QR Code da tela.")

    # ----------------------------------------------------
    # ABA 2: PAINEL GERADOR DE QR CODE (PAINEL FÍSICO)
    # ----------------------------------------------------
    with aba_admin:
        # Se NÃO estiver autenticado: exibe o campo de senha aberto
        if not st.session_state["admin_autenticado"]:
            with st.expander("🔑 Acesso Administrativo", expanded=True):
                senha_input = st.text_input("Digite a senha do painel:", type="password", key="pwd_input")
                if st.button("Acessar Painel", type="primary"):
                    if senha_input == ADMIN_PASSWORD:
                        st.session_state["admin_autenticado"] = True
                        st.rerun()
                    else:
                        st.error("❌ Senha incorreta.")
        
        # Se JÁ ESTIVER autenticado: recolhe a área administrativa e mostra o display limpo
        else:
            with st.expander("⚙️ Configurações do Painel (Clique para recolher/expandir)", expanded=False):
                st.success("✅ Painel Ativo")
                st.caption(f"📍 **URL configurada:** `{APP_URL}`")
                if st.button("🔒 Bloquear Painel / Sair"):
                    st.session_state["admin_autenticado"] = False
                    st.rerun()

            st.markdown("---")
            # Exibe o display do QR Code de forma limpa na tela
            renderizar_qr_code_auto()

if __name__ == "__main__":
    main()
