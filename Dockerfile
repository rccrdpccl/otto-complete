FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash git curl jq ca-certificates gnupg nodejs npm \
    && rm -rf /var/lib/apt/lists/*

RUN ARCH=$(uname -m) \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${ARCH}/docker-27.5.1.tgz" \
    | tar xz -C /usr/local/bin --strip=1 docker/docker

RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | gpg --dearmor -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y gh && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

ARG SUPERPOWERS_VERSION=b7a8f76985f1e93e75dd2f2a3b424dc731bd9d37
RUN git clone https://github.com/obra/superpowers.git /opt/superpowers \
    && cd /opt/superpowers && git checkout $SUPERPOWERS_VERSION && rm -rf .git

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

RUN useradd -m -s /bin/bash agent
USER agent
WORKDIR /home/agent/otto-complete

COPY --chown=agent:agent otto_complete/ otto_complete/
COPY --chown=agent:agent templates/ templates/
COPY --chown=agent:agent entrypoint.sh ./
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
