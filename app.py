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

# Chave secreta usada para assinar digitalmente os QR Codes (altere no .streamlit/secrets.toml em produção)
SECRET_KEY = st.secrets.get("SECRET_KEY", "chave_secreta_super_segura_123")
TEMPO_EXPIRACAO_MINUTOS = 3 # Validade máxima do QR Code em minutos

# SCOPES para permissão no Google Sheets e Drive
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# ==========================================
# FUNÇÕES DE AUTENTICAÇÃO E GOOGLE SHEETS
# ==========================================
@st.cache_resource
def conectar_google_sheets():
    """Conecta na API do Google Sheets usando as credenciais do Streamlit Secrets."""
    try:
        credentials_dict = dict(st.secrets["gcp_service_account"])
        credentials = Credentials.from_service_account_info(credentials_dict, scopes=SCOPES)
        client = gspread.authorize(credentials)
        return client
    except Exception as e:
        st.error(f"Erro ao conectar com Google Sheets: {e}")
        return None

def obter_aba_planilha(nome_aba: str):
    """Acessa uma aba específica da planilha informada nos secrets."""
    client = conectar_google_sheets()
    if client:
        sheet_id = st.secrets["SPREADSHEET_ID"]
        return client.open_by_key(sheet_id).worksheet(nome_aba)
    return None

def carregar_base_colaboradores() -> dict:
    """Busca a aba 'Colaboradores' no Google Sheets e retorna um de/para {Matricula: Nome}."""
    try:
        sheet = obter_aba_planilha("Colaboradores")
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        # Normaliza colunas para evitar erros de digitação
        df["Matricula"] = df["Matricula"].astype(str).str.strip()
        return dict(zip(df["Matricula"], df["Nome"]))
    except Exception as e:
        st.error(f"Erro ao carregar colaboradores do Google Sheets: {e}")
        return {}

def registrar_movimentacao(matricula: str, nome: str, telefone_id: str, acao: str):
    """Insere um novo registro de Retirada ou Devolução no Google Sheets."""
    sheet = obter_aba_planilha("Historico")
    timestamp_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    nova_linha = [timestamp_atual, matricula, nome, telefone_id, acao]
    sheet.append_row(nova_linha)

# ==========================================
# FUNÇÕES DO QR CODE DINÂMICO (TOKEN ANTIFRAUDE)
# ==========================================
def gerar_assinatura(timestamp_str: str) -> str:
    """Gera um hash HMAC para garantir que o QR Code não foi adulterado."""
    return hmac.new(
        SECRET_KEY.encode(),
        timestamp_str.encode(),
        hashlib.sha256
    ).hexdigest()[:10] # Retorna os 10 primeiros caracteres da assinatura

def validar_token(t_param: str, s_param: str) -> tuple[bool, str]:
    """Valida se o token do QR Code é autêntico e se não expirou."""
    if not t_param or not s_param:
        return False, "Link inválido. Escaneie o QR Code na base física."
    
    # 1. Valida a integridade da assinatura
    assinatura_esperada = gerar_assinatura(t_param)
    if not hmac.compare_digest(assinatura_esperada, s_param):
        return False, "Assinatura do QR Code é inválida ou foi alterada."
    
    # 2. Valida o tempo de expiração
    try:
        timestamp_qr = int(t_param)
        agora = int(datetime.now(timezone.utc).timestamp())
        diferenca_segundos = agora - timestamp_qr
        
        if diferenca_segundos < 0:
            return False, "Horário do servidor desalinhado."
        
        if diferenca_segundos > (TEMPO_EXPIRACAO_MINUTOS * 60):
            return False, f"⚠️ Este QR Code expirou há {int((diferenca_segundos - TEMPO_EXPIRACAO_MINUTOS*60)/60)} minutos. Por favor, escaneie o novo QR Code exibido na tela da base."
            
    except ValueError:
        return False, "Formato do parâmetro de tempo inválido."
        
    return True, "Token Válido"

def gerar_imagem_qr(url_base: str) -> bytes:
    """Cria um novo QR Code codificando a URL + Timestamp + Assinatura."""
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
# INTERFACE DO APP (STREAMLIT)
# ==========================================
def main():
    st.title("📱 Gestão de Telefones")
    
    aba_usuario, aba_admin = st.tabs(["📲 Formulário de Operação", "📺 Painel Físico / Gerador de QR Code"])

    # ----------------------------------------------------
    # ABA 1: FORMULÁRIO DO COLABORADOR
    # ----------------------------------------------------
    with aba_usuario:
        # Pega parâmetros passados via URL ao escanear o QR Code
        params = st.query_params
        t_param = params.get("t")
        s_param = params.get("s")
        
        token_valido, mensagem_erro = validar_token(t_param, s_param)
        
        if not token_valido:
            st.error(mensagem_erro)
            st.info("💡 Dirija-se até a base presencial de telefones e escaneie o QR Code atualizado exibido no monitor.")
        else:
            st.success("🔒 Acesso liberado via QR Code presencial.")
            st.markdown("---")
            
            # Carrega colaboradores do Google Sheets
            base_colaboradores = carregar_base_colaboradores()
            
            with st.form("form_registro", clear_on_submit=True):
                tipo_acao = st.radio("Selecione a ação:", ["Retirada", "Devolução"], horizontal=True)
                matricula = st.text_input("Matrícula do Colaborador").strip()
                codigo_tel = st.text_input("Código do Telefone (ex: TEL-01)").strip().upper()
                
                submit = st.form_submit_button("Confirmar Operação", type="primary")
                
                if submit:
                    if not matricula or not codigo_tel:
                        st.warning("⚠️ Preencha a Matrícula e o Código do Telefone.")
                    elif matricula not in base_colaboradores:
                        st.error(f"❌ Matrícula '{matricula}' não cadastrada no sistema. Fale com a supervisão.")
                    else:
                        nome_colaborador = base_colaboradores[matricula]
                        registrar_movimentacao(matricula, nome_colaborador, codigo_tel, tipo_acao)
                        
                        st.balloons()
                        st.success(f"✅ **{tipo_acao}** registrada com sucesso!\n- **Colaborador:** {nome_colaborador}\n- **Aparelho:** {codigo_tel}")

    # ----------------------------------------------------
    # ABA 2: PAINEL GERADOR DE QR CODE (Fica aberto em um tablet/monitor na base)
    # ----------------------------------------------------
    with aba_admin:
        st.subheader("📺 Display do QR Code Presencial")
        st.caption("Deixe esta aba aberta no monitor local da empresa. Atualize o QR Code periodicamente.")
        
        url_app = st.text_input("URL pública do App", value="https://seu-app.streamlit.app")
        
        if st.button("🔄 Gerar Novo QR Code Agora"):
            st.rerun()

        # Gera o QR Code com a hora exata deste instante
        qr_bytes = gerar_imagem_qr(url_app)
        
        col1, col2 = st.columns([2, 1])
        with col1:
            st.image(qr_bytes, caption=f"Válido por {TEMPO_EXPIRACAO_MINUTOS} minutos a partir do momento de geração.", width=320)
        with col2:
            st.markdown("### Instruções:")
            st.write("1. Abra a câmera do celular.")
            st.write("2. Escaneie o QR Code ao lado.")
            st.write("3. Preencha sua matrícula para retirar/devolver.")

if __name__ == "__main__":
    main()
