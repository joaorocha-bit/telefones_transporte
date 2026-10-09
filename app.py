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
TEMPO_EXPIRACAO_MINUTOS = 2

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

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

def carregar_status_telefones() -> pd.DataFrame:
    try:
        sheet_telefones = obter_aba_planilha("Controle_Telefone")
        sheet_historico = obter_aba_planilha("Historico")
        
        df_telefones = pd.DataFrame(sheet_telefones.get_all_records())
        df_historico = pd.DataFrame(sheet_historico.get_all_records())
        
        if df_telefones.empty or "Codigo_Telefone" not in df_telefones.columns:
            return pd.DataFrame()
        
        df_telefones["Codigo_Telefone"] = df_telefones["Codigo_Telefone"].astype(str).str.strip().str.upper()
        
        status_lista = []
        
        if not df_historico.empty and "Codigo_Telefone" in df_historico.columns:
            df_historico["Codigo_Telefone"] = df_historico["Codigo_Telefone"].astype(str).str.strip().str.upper()
            
            for cod in df_telefones["Codigo_Telefone"]:
                movs = df_historico[df_historico["Codigo_Telefone"] == cod]
                
                if not movs.empty:
                    ultima_mov = movs.iloc[-1]
                    acao = str(ultima_mov.get("Acao", "")).strip()
                    nome = str(ultima_mov.get("Nome", "")).strip()
                    data_hora = str(ultima_mov.get("Data_Hora", "")).strip()
                    
                    if acao.lower() == "retirada":
                        status = "🔴 Em Uso"
                        responsavel = nome
                    else:
                        status = "🟢 Disponível"
                        responsavel = "-"
                else:
                    status = "🟢 Disponível"
                    responsavel = "-"
                    data_hora = "-"
                    
                status_lista.append({
                    "Código Telefone": cod,
                    "Status": status,
                    "Responsável Atual": responsavel,
                    "Última Atualização": data_hora
                })
        else:
            for cod in df_telefones["Codigo_Telefone"]:
                status_lista.append({
                    "Código Telefone": cod,
                    "Status": "🟢 Disponível",
                    "Responsável Atual": "-",
                    "Última Atualização": "-"
                })
                
        return pd.DataFrame(status_lista)
    except Exception as e:
        st.error(f"Erro ao processar status dos telefones: {e}")
        return pd.DataFrame()

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
# COMPONENTE DE AUTENTICAÇÃO ADMINISTRATIVA (CHAVES ÚNICAS)
# ==========================================
def verificar_login_admin(key_suffix: str = "default") -> bool:
    """Gerencia a autenticação das abas restritas usando chaves dinâmicas."""
    if not st.session_state["admin_autenticado"]:
        with st.expander("🔑 Acesso Administrativo Requerido", expanded=True):
            senha_input = st.text_input("Digite a senha do painel:", type="password", key=f"pwd_{key_suffix}")
            if st.button("Acessar", type="primary", key=f"btn_login_{key_suffix}"):
                if senha_input == ADMIN_PASSWORD:
                    st.session_state["admin_autenticado"] = True
                    st.rerun()
                else:
                    st.error("❌ Senha incorreta.")
        return False
    else:
        with st.expander("⚙️ Sessão Administrativa Ativa (Clique para fechar/sair)", expanded=False):
            st.success("✅ Você está autenticado como Administrador.")
            if st.button("🔒 Bloquear Painel / Sair", key=f"btn_logout_{key_suffix}"):
                st.session_state["admin_autenticado"] = False
                st.rerun()
        return True

# ==========================================
# INTERFACE DO APP
# ==========================================
def main():
    st.title("📱 Gestão de Telefones")
    
    aba_usuario, aba_admin, aba_status = st.tabs([
        "📲 Formulário de Operação", 
        "📺 Painel Físico / Gerador", 
        "📊 Status dos Telefones"
    ])

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
    # ABA 2: PAINEL GERADOR DE QR CODE
    # ----------------------------------------------------
    with aba_admin:
        if verificar_login_admin(key_suffix="qr_code_tab"):
            st.markdown("---")
            renderizar_qr_code_auto()

    # ----------------------------------------------------
    # ABA 3: STATUS DOS TELEFONES
    # ----------------------------------------------------
    with aba_status:
        if verificar_login_admin(key_suffix="status_tab"):
            st.subheader("📋 Inventário e Status dos Telefones")
            
            col_ref, _ = st.columns([1, 3])
            with col_ref:
                if st.button("🔄 Atualizar Dados", use_container_width=True, key="btn_refresh_status"):
                    st.rerun()

            with st.spinner("Consultando dados da planilha..."):
                df_status = carregar_status_telefones()

            if df_status.empty:
                st.warning("⚠️ Nenhum telefone encontrado na aba 'Controle_Telefone' ou erro na leitura.")
            else:
                total_tels = len(df_status)
                em_uso = len(df_status[df_status["Status"] == "🔴 Em Uso"])
                disponiveis = len(df_status[df_status["Status"] == "🟢 Disponível"])
                
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Cadastrado", total_tels)
                m2.metric("🔴 Em Uso", em_uso)
                m3.metric("🟢 Disponíveis", disponiveis)
                
                st.markdown("---")
                
                busca = st.text_input("🔍 Buscar por Código do Telefone ou Colaborador:", key="input_busca_tel").strip().lower()
                
                if busca:
                    df_exibicao = df_status[
                        df_status["Código Telefone"].str.lower().str.contains(busca) |
                        df_status["Responsável Atual"].str.lower().str.contains(busca)
                    ]
                else:
                    df_exibicao = df_status

                st.dataframe(
                    df_exibicao,
                    use_container_width=True,
                    hide_index=True
                )

if __name__ == "__main__":
    main()
