Setup rápido do ambiente

Windows (PowerShell):

1. Abra PowerShell na pasta do projeto.
2. Rode:

```powershell
.\scripts\setup_env.ps1
```

Isso criará `.venv`, instalará as dependências listadas em `requirements.txt` e exibirá comandos para ativar e executar o app.

Se preferir usar a venv manualmente:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

Observação: se `groq` for um pacote privado, ajuste `requirements.txt` para apontar para a fonte correta ou instale o pacote manualmente.
