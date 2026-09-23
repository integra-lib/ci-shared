# CI image for all integra-lib components.
#
# Build and push to each project's container registry:
#
#   docker build -t registry.gitlab.integrasources.com/<project-path>:arch .
#   docker push registry.gitlab.integrasources.com/<project-path>:arch
#
# Or build once and tag for multiple projects.

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

# Install clang-format (may be in a separate package)
RUN pacman -S --noconfirm clang-format || true

# Install pre-commit
RUN pip install --break-system-packages pre-commit

# Verify installation
RUN cmake --version && \
    g++ --version && \
    clang++ --version && \
    clang-format --version && \
    pre-commit --version && \
    npm --version

WORKDIR /build
