import streamlit as st
import qrcode
import pandas as pd
from datetime import datetime, timezone
import io
import hmac
import hashlib
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# CONFIGURAÇÃO E SEGURANÇA
# ==========================================
st.set_page_config(page_title="Controle de Telefones", page_icon="📱", layout="centered")

# URL fixa do aplicativo
APP_URL = st.secrets.get("APP_URL", "https://telefonestransporte-ndzmusne7o33caaqh6tcwz.streamlit.app/")

SECRET_KEY = st.secrets.get("SECRET_KEY", "chave_secreta_super_segura_123")
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "admin123")
TEMPO_EXPIRACAO_MINUTOS = 3 

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

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
    timestamp_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
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
    # Remove a barra no final caso exista para evitar url com barras duplas
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
# INTERFACE DO APP
# ==========================================
def main():
    st.title("📱 Gestão de Telefones")
    
    aba_usuario, aba_admin = st.tabs(["📲 Formulário de Operação", "🔒 Painel Físico / Gerador"])

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
                    # Revalida o tempo EXATAMENTE no momento do clique no botão
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
                        
                        # Queima o token limpando os parâmetros da URL para evitar reutilização
                        st.query_params.clear()
                        
                        st.balloons()
                        st.success(f"✅ **{tipo_acao}** registrada com sucesso!\n- **Colaborador:** {nome_colaborador}\n- **Aparelho:** {codigo_tel}")
                        st.info("Para registrar outro aparelho, escaneie novamente o QR Code da tela.")

    # ----------------------------------------------------
    # ABA 2: PAINEL GERADOR DE QR CODE (PROTEGIDO POR SENHA)
    # ----------------------------------------------------
    with aba_admin:
        st.subheader("🔒 Acesso Administrativo")
        senha_digitada = st.text_input("Digite a senha do painel para exibir o QR Code:", type="password")
        
        if senha_digitada == ADMIN_PASSWORD:
            st.success("Acesso autorizado.")
            st.caption("Deixe esta tela aberta no monitor da base física.")
            
            # Mostra a URL configurada apenas para conferência
            st.caption(f"📍 **URL de destino:** `{APP_URL}`")
            
            if st.button("🔄 Gerar Novo QR Code Agora"):
                st.rerun()

            # Gera o QR Code utilizando a URL fixa
            qr_bytes = gerar_imagem_qr(APP_URL)
            
            col1, col2 = st.columns([2, 1])
            with col1:
                st.image(qr_bytes, caption=f"Válido por {TEMPO_EXPIRACAO_MINUTOS} minutos.", width=320)
            with col2:
                st.markdown("### Instruções:")
                st.write("1. Abra a câmera do celular.")
                st.write("2. Escaneie o QR Code.")
                st.write("3. Preencha o formulário.")
        elif senha_digitada:
            st.error("❌ Senha incorreta.")

if __name__ == "__main__":
    main()
