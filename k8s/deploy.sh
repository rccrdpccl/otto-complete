#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CLUSTER_NAME="${KIND_CLUSTER:-otto-complete}"
IMAGE_NAME="otto-complete:latest"

echo "=== Building container image ==="
podman build -t "$IMAGE_NAME" "$PROJECT_DIR"

echo "=== Creating kind cluster (if needed) ==="
if ! kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    kind create cluster --name "$CLUSTER_NAME"
else
    echo "Cluster '$CLUSTER_NAME' already exists"
fi

echo "=== Loading image into kind ==="
podman save "$IMAGE_NAME" -o /tmp/otto-complete.tar
kind load image-archive /tmp/otto-complete.tar --name "$CLUSTER_NAME"
rm -f /tmp/otto-complete.tar

echo "=== Applying manifests ==="
kubectl apply -f "$SCRIPT_DIR/namespace.yaml"
kubectl apply -f "$SCRIPT_DIR/secrets.yaml"
kubectl apply -f "$SCRIPT_DIR/configmap.yaml"
kubectl apply -f "$SCRIPT_DIR/deployment.yaml"

echo "=== Done ==="
echo "Deployment applied to cluster '$CLUSTER_NAME' in namespace 'otto-complete'"
echo ""
echo "Useful commands:"
echo "  kubectl get deployment -n otto-complete"
echo "  kubectl get pods -n otto-complete"
echo "  kubectl logs -f deployment/otto-complete -n otto-complete"
echo "  kubectl rollout restart deployment/otto-complete -n otto-complete"
