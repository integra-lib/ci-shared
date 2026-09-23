# CI image for all integra-lib components.

FROM archlinux:latest

# Install build tools and dependencies
RUN pacman -Syu --noconfirm \
    base-devel \
    cmake \
    ninja \
    clang \
    llvm \
    git \
    openssh \
    npm \
    python \
    python-pip \
    && pacman -Scc --noconfirm

# Install pre-commit
RUN pip install --break-system-packages pre-commit

# Fetch googletest for offline builds
RUN mkdir -p /opt/deps && \
    git clone --depth 1 --branch v1.15.2 https://github.com/google/googletest.git /opt/deps/googletest-src || \
    echo "googletest fetch failed - builds will need internet access"

# Pre-install pre-commit hooks
COPY .pre-commit-config.yaml /tmp/
RUN cd /tmp && \
    git init -q && \
    git add .pre-commit-config.yaml && \
    pre-commit install-hooks || \
    echo "pre-commit hooks install failed"

# Verify installation
RUN cmake --version && \
    g++ --version && \
    clang++ --version && \
    clang-format --version && \
    ssh -V && \
    pre-commit --version && \
    npm --version

WORKDIR /build
