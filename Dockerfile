FROM ubuntu:20.04

# Prevenir prompts interativos durante a instalação do apt
ENV DEBIAN_FRONTEND=noninteractive

# Instalar sudo, iproute2 e utilitários básicos de rede frequentemente usados no Mininet
RUN apt-get update && apt-get install -y \
    sudo \
    iproute2 \
    iputils-ping \
    net-tools \
    dos2unix \
    git \
    wget \
    curl \
    build-essential \
    cmake \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*  

# Definir a pasta de trabalho
WORKDIR /workspace

# Copiar apenas o script de setup primeiro para aproveitar o cache do Docker
COPY scripts/setup_ubuntu.sh /tmp/setup_ubuntu.sh

# Pode ajustar o número de JOBS se quiser acelerar o build (ex: ARG JOBS=8)
ARG JOBS=4
ENV JOBS=${JOBS}

# Executar o script de setup (compila p4c, PI, bmv2 e instala dependências)
RUN dos2unix /tmp/setup_ubuntu.sh && \
    chmod +x /tmp/setup_ubuntu.sh && \
    USER=root bash /tmp/setup_ubuntu.sh

# Copia todos os arquivos locais para evitar problemas de volume mount no Windows
COPY . /workspace

# Comando padrão para manter o contêiner rodando em background
CMD ["tail", "-f", "/dev/null"]
