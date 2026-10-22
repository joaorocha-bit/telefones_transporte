import streamlit as st
import streamlit.components.v1 as components
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
st.set_page_config(page_title="Controle de Telefones", page_icon="📱", layout="wide")

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

if "modo_kiosk" not in st.session_state:
    st.session_state["modo_kiosk"] = False

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

@st.cache_data(ttl=600)
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
    
    st.cache_data.clear()

def consultar_status_telefone_especifico(codigo_tel: str) -> tuple[str, str, bool]:
    try:
        sheet_telefones = obter_aba_planilha("Controle_Telefone")
        sheet_historico = obter_aba_planilha("Historico")
        
        df_telefones = pd.DataFrame(sheet_telefones.get_all_records())
        
        if df_telefones.empty or "Codigo_Telefone" not in df_telefones.columns:
            return "Disponível", "", False
        
        df_telefones["Codigo_Telefone"] = df_telefones["Codigo_Telefone"].astype(str).str.strip().str.upper()
        codigo_tel_upper = codigo_tel.strip().upper()
        
        if codigo_tel_upper not in df_telefones["Codigo_Telefone"].values:
            return "Não Encontrado", "", False
        
        df_historico = pd.DataFrame(sheet_historico.get_all_records())
        
        if not df_historico.empty and "Codigo_Telefone" in df_historico.columns:
            df_historico["Codigo_Telefone"] = df_historico["Codigo_Telefone"].astype(str).str.strip().str.upper()
            movs = df_historico[df_historico["Codigo_Telefone"] == codigo_tel_upper]
            
            if not movs.empty:
                ultima_mov = movs.iloc[-1]
                acao = str(ultima_mov.get("Acao", "")).strip()
                nome = str(ultima_mov.get("Nome", "")).strip()
                
                if acao.lower() == "retirada":
                    return "Em Uso", nome, True
                else:
                    return "Disponível", "", True

        return "Disponível", "", True
    except Exception as e:
        st.error(f"Erro ao verificar status do telefone: {e}")
        return "Erro", "", False

@st.cache_data(ttl=15)
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

def registrar_devolucao_esquecimento(codigos_telefones: list) -> list:
    sheet_historico = obter_aba_planilha("Historico")
    df_historico = pd.DataFrame(sheet_historico.get_all_records())
    
    processados = []
    
    if not df_historico.empty and "Codigo_Telefone" in df_historico.columns:
        df_historico["Codigo_Telefone"] = df_historico["Codigo_Telefone"].astype(str).str.strip().str.upper()
        
        for cod in codigos_telefones:
            cod_upper = cod.strip().upper()
            movs = df_historico[df_historico["Codigo_Telefone"] == cod_upper]
            
            if not movs.empty:
                ultima_mov = movs.iloc[-1]
                matricula = str(ultima_mov.get("Matricula", "")).strip()
                nome_orig = str(ultima_mov.get("Nome", "")).strip()
                
                nome_limpo = nome_orig.replace("(Esquecimento)", "").strip()
                nome_final = f"{nome_limpo} (Esquecimento)"
                
                registrar_movimentacao(matricula, nome_final, cod_upper, "Devolução")
                processados.append({
                    "codigo": cod_upper,
                    "matricula": matricula,
                    "nome": nome_final
                })
            else:
                registrar_movimentacao("0000", "Desconhecido (Esquecimento)", cod_upper, "Devolução")
                processados.append({
                    "codigo": cod_upper,
                    "matricula": "0000",
                    "nome": "Desconhecido (Esquecimento)"
                })
                
    return processados

# ==========================================
# FUNÇÕES DE VALIDAÇÃO DO QR CODE E ADMIN
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
    
    qr = qrcode.QRCode(version=1, box_size=12, border=4)
    qr.add_data(url_com_token)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="#1E1E1E", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def verificar_login_admin(key_suffix: str = "default") -> bool:
    if not st.session_state.get("admin_autenticado", False):
        with st.expander("🔑 Acesso Administrativo Requerido", expanded=True):
            senha_input = st.text_input("Digite a senha do painel:", type="password", key=f"pwd_{key_suffix}")
            if st.button("Acessar Painel", type="primary", key=f"btn_login_{key_suffix}"):
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
# PAINEL DA BASE (QR CODE + STATUS DOS TELEFONES)
# ==========================================
@st.fragment(run_every="60s")
def renderizar_painel_base(kiosk_mode: bool = False):
    col_qr, col_status = st.columns([1, 1.1])
    
    # --- COLUNA DA ESQUERDA: QR CODE ---
    with col_qr:
        st.subheader("📱 QR Code para Retirada / Devolução")
        qr_bytes = gerar_imagem_qr(APP_URL)
        st.image(qr_bytes, caption=f"🔄 Atualizado automaticamente • Válido por {TEMPO_EXPIRACAO_MINUTOS} min.", width=280 if not kiosk_mode else 320)
        
        st.markdown("**Instruções:**")
        st.markdown("1. Abra a câmera do seu celular  \n2. Escaneie o QR Code acima  \n3. Informe sua matrícula e código do telefone")
        
        if not kiosk_mode:
            st.markdown("---")
            if st.button("Entrar em Modo Tela Cheia", type="secondary", use_container_width=True):
                st.session_state["modo_kiosk"] = True
                st.rerun()

    # --- COLUNA DA DIREITA: STATUS DOS TELEFONES ---
    with col_status:
        st.subheader("📋 Status dos Telefones")
        
        df_status = carregar_status_telefones()
        
        if df_status.empty:
            st.warning("⚠️ Nenhum telefone encontrado na aba 'Controle_Telefone' ou erro na leitura.")
        else:
            st.dataframe(
                df_status,
                use_container_width=True,
                hide_index=True,
                height=380
            )
            
            # --- SEÇÃO ADMINISTRATIVA: DEVOLUÇÃO POR ESQUECIMENTO ---
            with st.expander("🛠️ Marcar Devolução por Esquecimento"):
                st.write("Selecione os aparelhos que não foram devolvidos ao fim do turno para registrar a devolução com 'Esquecimento'.")
                
                telefones_em_uso = df_status[df_status["Status"] == "🔴 Em Uso"]["Código Telefone"].tolist()
                
                if not telefones_em_uso:
                    st.info("🟢 Nenhum telefone consta em uso no momento.")
                else:
                    selecionados = st.multiselect(
                        "Selecione o(s) telefone(s) para registrar devolução:",
                        options=telefones_em_uso,
                        key="select_esquecimento"
                    )
                    
                    if st.button("Confirmar Devolução por Esquecimento", type="primary"):
                        if not selecionados:
                            st.warning("⚠️ Selecione pelo menos um telefone.")
                        else:
                            with st.spinner("Registrando devoluções no histórico..."):
                                processados = registrar_devolucao_esquecimento(selecionados)
                            
                            st.success(f"✅ Devolução registrada com sucesso para {len(processados)} telefone(s)!")
                            for p in processados:
                                st.write(f"• **Telefone:** {p['codigo']} | **Atribuído a:** {p['nome']} (Matrícula: {p['matricula']})")
                            
                            st.rerun()

# ==========================================
# INTERFACE PRINCIPAL DO APP
# ==========================================
def main():
    if "ultima_operacao" not in st.session_state:
    st.session_state["ultima_operacao"] = None
    
    if st.session_state.get("modo_kiosk", False):
        st.markdown("""
            <style>
                header {visibility: hidden !important;}
                footer {visibility: hidden !important;}
                .stTabs {display: none !important;}
                .block-container {padding-top: 0.5rem !important; padding-bottom: 0rem !important; max-width: 98% !important;}
                h1 {display: none !important;}
            </style>
        """, unsafe_allow_html=True)
        
        components.html("""
            <script>
                var elem = window.parent.document.documentElement;
                if (!window.parent.document.fullscreenElement) {
                    if (elem.requestFullscreen) { elem.requestFullscreen(); }
                    else if (elem.webkitRequestFullscreen) { elem.webkitRequestFullscreen(); }
                }
            </script>
        """, height=0)

        col_top, col_btn = st.columns([5, 1])
        with col_top:
            st.title("Painel da Base - QR Code e Status dos Telefones")
        with col_btn:
            if st.button("Sair da Tela Cheia", type="secondary", use_container_width=True):
                st.session_state["modo_kiosk"] = False
                st.rerun()

        st.markdown("---")
        renderizar_painel_base(kiosk_mode=True)
        return

    st.title("Gestão de Telefones")
    
    aba_usuario, aba_base = st.tabs([
        "Formulário de Operação", 
        "Painel Base (QR Code & Status)"
    ])

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
        
        # clear_on_submit=True limpa os campos imediatamente ao clicar
        with st.form("form_registro", clear_on_submit=True):
            tipo_acao = st.radio("Selecione a ação:", ["Retirada", "Devolução"], horizontal=True)
            matricula = st.text_input("Matrícula do Colaborador (Somente números).").strip()
            codigo_tel = st.text_input("Código do Telefone.").strip().upper()
            
            submit = st.form_submit_button("Confirmar Operação", type="primary")
            
            if submit:
                # 🎯 TRAVA DE IDEMPOTÊNCIA: Gera uma chave única da tentativa
                chave_operacao = f"{tipo_acao}_{matricula}_{codigo_tel}"
                
                # Se for um duplo clique da MESMA operação recém-feita, apenas reexibe sucesso
                if st.session_state.get("ultima_operacao") == chave_operacao:
                    st.success(f"✅ **{tipo_acao}** já confirmada com sucesso!")
                    st.info("Para registrar outro aparelho, escaneie novamente o QR Code da tela.")
                else:
                    re_valido, re_msg = validar_token(t_param, s_param)
                    
                    if not re_valido:
                        st.error("⏱️ O tempo do QR Code expirou enquanto você preenchia. Escaneie novamente na base.")
                    elif not matricula or not codigo_tel:
                        st.warning("⚠️ Preencha a Matrícula e o Código do Telefone.")
                    elif matricula not in base_colaboradores:
                        st.error(f"❌ Matrícula '{matricula}' não encontrada. Verifique com a supervisão.")
                    else:
                        status_atual, responsavel_atual, existe_no_cadastro = consultar_status_telefone_especifico(codigo_tel)
                        
                        if not existe_no_cadastro:
                            st.error(f"❌ O código de telefone **'{codigo_tel}'** não consta cadastrado no sistema (aba Controle_Telefone).")
                        elif tipo_acao == "Retirada" and status_atual == "Em Uso":
                            st.error(f"❌ O telefone **'{codigo_tel}'** já está em uso por **{responsavel_atual}**. Não é possível realizar uma nova retirada.")
                        elif tipo_acao == "Devolução" and status_atual == "Disponível":
                            st.error(f"❌ O telefone **'{codigo_tel}'** consta como devolvido/disponível. Não é possível registrar devolução.")
                        else:
                            nome_colaborador = base_colaboradores[matricula]
                            
                            # Feedback visual imediato durante a gravação
                            with st.spinner("Registrando operação..."):
                                registrar_movimentacao(matricula, nome_colaborador, codigo_tel, tipo_acao)
                                # Salva a chave para bloquear cliques duplos subsequentes
                                st.session_state["ultima_operacao"] = chave_operacao
                            
                            st.query_params.clear()
                            st.success(f"✅ **{tipo_acao}** registrada com sucesso!\n- **Colaborador:** {nome_colaborador}\n- **Aparelho:** {codigo_tel}")
                            st.info("Para registrar outro aparelho, escaneie novamente o QR Code da tela.")
    with aba_base:
        if verificar_login_admin(key_suffix="painel_base"):
            renderizar_painel_base(kiosk_mode=False)

if __name__ == "__main__":
    main()
