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
    npm \
    python \
    python-pip \
    && pacman -Scc --noconfirm

# Install pre-commit
RUN pip install --break-system-packages pre-commit

# Pre-install googletest for offline builds
COPY googletest-src /opt/deps/googletest-src

# Verify installation
RUN cmake --version && \
    g++ --version && \
    clang++ --version && \
    clang-format --version && \
    pre-commit --version && \
    npm --version

WORKDIR /build
