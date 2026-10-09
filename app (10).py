import streamlit as st
import qrcode
import pandas as pd
from datetime import datetime
import io
import os

# Configuração da página
st.set_page_config(page_title="Controle de Telefones", page_icon="📱", layout="centered")

# ==========================================
# 1. SIMULAÇÃO DE BANCO DE DADOS (Pode ser substituído por consulta a banco ou planilha)
# ==========================================
COLABORADORES = {
    "1001": "Ana Silva",
    "1002": "Carlos Eduardo",
    "1003": "Mariana Costa"
}

ARQUIVO_PLANILHA = "registro_retiradas.csv" # Usando CSV local para MVP

def salvar_registro(matricula, nome, telefone_id):
    """Salva o registro na planilha/CSV com o timestamp atual."""
    novo_registro = pd.DataFrame([{
        "Matricula": matricula,
        "Colaborador": nome,
        "Codigo_Telefone": telefone_id,
        "Data_Hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    }])
    
    if os.path.exists(ARQUIVO_PLANILHA):
        df = pd.read_csv(ARQUIVO_PLANILHA)
        df = pd.concat([df, novo_registro], ignore_index=True)
    else:
        df = novo_registro
        
    df.to_csv(ARQUIVO_PLANILHA, index=False)

def gerar_qr_code(url_base, token_aleatorio=""):
    """Gera a imagem do QR Code em bytes para o Streamlit renderizar."""
    url_final = f"{url_base}?token={token_aleatorio}" if token_aleatorio else url_base
    
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(url_final)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

# ==========================================
# 2. INTERFACE DO APP (Frontend)
# ==========================================
def main():
    st.title("📱 Sistema de Retirada de Telefones")
    
    # Divide a interface em duas abas
    aba_form, aba_admin = st.tabs(["📋 Formulário de Retirada", "⚙️ Gerador de QR Code (Admin)"])

    # --- ABA 1: FORMULÁRIO ---
    with aba_form:
        st.markdown("### Registre a retirada do equipamento")
        
        with st.form("form_retirada", clear_on_submit=True):
            matricula = st.text_input("Matrícula do Colaborador")
            codigo_tel = st.text_input("Código do Telefone (Ex: TEL-01)")
            
            submit = st.form_submit_button("Registrar Retirada", type="primary")
            
            if submit:
                if not matricula or not codigo_tel:
                    st.warning("⚠️ Preencha todos os campos antes de registrar.")
                elif matricula not in COLABORADORES:
                    st.error("❌ Matrícula não encontrada no sistema. Verifique o número digitado.")
                else:
                    nome_colaborador = COLABORADORES[matricula]
                    salvar_registro(matricula, nome_colaborador, codigo_tel)
                    st.success(f"✅ Retirada registrada com sucesso para {nome_colaborador}!")

    # --- ABA 2: ADMIN / GERADOR DE QR CODE ---
    with aba_admin:
        st.markdown("### Gerar Novo QR Code")
        st.info("Este QR Code enviará o usuário diretamente para este aplicativo.")
        
        # Como o Streamlit rodará na web, precisamos da URL real onde ele está hospedado
        url_app = st.text_input("URL do App (Ex: https://meu-app-telefone.streamlit.app/)", value="https://seusite.com")
        
        if st.button("Gerar QR Code"):
            # O timestamp gera a aleatoriedade solicitada no prompt
            token_aleatorio = datetime.now().strftime("%Y%m%d%H%M%S")
            qr_bytes = gerar_qr_code(url_app, token_aleatorio)
            
            st.image(qr_bytes, caption="Escaneie para acessar o formulário", width=300)
            st.download_button(
                label="📥 Baixar QR Code",
                data=qr_bytes,
                file_name=f"QR_Retirada_{token_aleatorio}.png",
                mime="image/png"
            )

if __name__ == "__main__":
    main()