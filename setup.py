"""Script de setup inicial."""
import subprocess
import sys

def main():
    print("Instalando dependências...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    print("Instalando navegador Playwright...")
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    print("\n✓ Setup concluído!")
    print("\nPróximos passos:")
    print("  1. Edite config/settings.yaml com seu ICP e mensagens")
    print("  2. python main.py save-session   # Faz login e salva sessão")
    print("  3. python main.py discover       # Busca perfis")
    print("  4. python main.py validate       # Qualifica perfis")
    print("  5. python main.py outreach       # Envia convites")
    print("  6. python main.py monitor        # Checa aceites e envia DM1")

if __name__ == "__main__":
    main()
