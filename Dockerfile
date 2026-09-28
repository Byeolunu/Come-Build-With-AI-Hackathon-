FROM python:3.13-slim

RUN useradd -m -s /bin/bash python

EXPOSE 3000
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ADD  . /app

# Install dependencies using uv
RUN uv sync --frozen --no-cache

# Ensure python user owns the app directory and has a writable home
RUN chown -R python:python /app /home/python

ARG COMMIT_SHA=<not-specified>
RUN echo "CivicPilot: $COMMIT_SHA" >> ./commit.sha

LABEL maintainer="%CUSTOM_PLUGIN_CREATOR_USERNAME%" \
      name="CivicPilot" \
      description="%CUSTOM_PLUGIN_SERVICE_DESCRIPTION%" \
      eu.mia-platform.url="https://www.mia-platform.eu" \
      eu.mia-platform.version="0.6.0"

# Disable uv cache at runtime to avoid permission issues on HF Spaces
ENV UV_NO_CACHE=1

USER python

CMD ["uv", "run", "python", "-m", "src.app"]
