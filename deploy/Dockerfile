# The container Cloud Run runs. Built by `gcloud builds submit`, from the
# repository root — so every COPY path below is relative to the root, not to
# deploy/.
#
# Two things about this image are not obvious and both have bitten already:
#
# `static/` is not part of the wheel. `pyproject.toml` packages `src/openproj`
# and nothing else, so an installed layout has no vendored cytoscape and no
# typeface, and `_static_dir` resolves past site-packages to a directory that
# does not exist. Every page then works except `/graph`, which 500s on its first
# request. Hence the explicit COPY and OPENPROJ_STATIC below: the code offers
# that variable precisely so a deployment can say where they are instead of
# hoping, and this is the deployment.
#
# The plan lives on a writable path that is NOT the image. Cloud Run's
# filesystem is in-memory and the service scales to zero, so /srv/plan.git is
# empty on every cold start and boot.py clones it back from the remote. That is
# the design, not a workaround: the durable copy is the git remote.

FROM python:3.12-slim

# Bytecode written at import time into a read-only layer is wasted work, and an
# unbuffered stream is the difference between seeing "cloning ..." in the logs
# during a cold start and seeing it after the process exits.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies resolve from wheels: pygit2 ships manylinux wheels with libgit2
# inside them, and cryptography likewise, so this image needs no compiler and no
# apt install. If either ever stops publishing a wheel for this Python, the
# build fails loudly here rather than producing a subtly different image.
COPY pyproject.toml LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY static ./static
COPY deploy/boot.py ./boot.py

ENV OPENPROJ_STATIC=/app/static \
    OPENPROJ_REPO=/srv/plan.git

# Not root. The one directory the process writes is the clone, so that is the
# one directory it owns.
RUN useradd --uid 10001 --create-home openproj \
    && mkdir -p /srv \
    && chown openproj:openproj /srv
USER openproj

# Cloud Run sets PORT; boot.py reads it and defaults to 8080 for a local run.
EXPOSE 8080
CMD ["python", "/app/boot.py"]
