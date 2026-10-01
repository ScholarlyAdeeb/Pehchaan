#!/usr/bin/env bash
# PEHCHAAN audit ledger on Hyperledger Fabric 2.5.
#
#   ./network.sh up        create identities, start orderer + peer, create the
#                          channel, deploy the auditledger chaincode
#   ./network.sh down      stop the containers (ledger data is kept)
#   ./network.sh destroy   stop and delete the ledger data and identities
#   ./network.sh status    containers, channel height, committed chaincode
#
# Needs only Docker. Every Fabric tool runs inside the hyperledger/fabric-tools
# image, so nothing is installed on the host. Works from Git Bash on Windows.
set -euo pipefail

cd "$(dirname "$0")"
export MSYS_NO_PATHCONV=1                      # Git Bash: do not rewrite /container/paths
ROOT="$(pwd -W 2>/dev/null || pwd)"            # a path Docker Desktop can mount
NET="$ROOT/network"
CC_SRC="$ROOT/chaincode/auditledger"

FABRIC_VERSION=2.5
CHANNEL=pehchaan
CC_NAME=auditledger
CC_VERSION="${CC_VERSION:-1.0}"
CC_SEQUENCE="${CC_SEQUENCE:-1}"
DOCKER_NET=pehchaan_fabric

ORDERER=orderer.pehchaan.local
PEER=peer0.ssb.pehchaan.local
ORDERER_TLS=/net/organizations/ordererOrganizations/pehchaan.local/orderers/$ORDERER/tls
PEER_ORG=/net/organizations/peerOrganizations/ssb.pehchaan.local

compose() { docker compose -f "$NET/docker-compose.yaml" "$@"; }

# Runs a Fabric CLI command in the tools image, as the SSB organisation admin.
tools() {
  local net_args=()
  docker network inspect "$DOCKER_NET" >/dev/null 2>&1 && net_args=(--network "$DOCKER_NET")
  docker run --rm "${net_args[@]}" \
    -v "$NET:/net" -v "$CC_SRC:/cc" -w /net \
    -e FABRIC_CFG_PATH="${TOOLS_CFG:-/etc/hyperledger/fabric}" \
    -e CORE_PEER_TLS_ENABLED=true \
    -e CORE_PEER_LOCALMSPID=SSBMSP \
    -e CORE_PEER_ADDRESS=$PEER:7051 \
    -e CORE_PEER_TLS_ROOTCERT_FILE=$PEER_ORG/peers/$PEER/tls/ca.crt \
    -e CORE_PEER_MSPCONFIGPATH=$PEER_ORG/users/Admin@ssb.pehchaan.local/msp \
    hyperledger/fabric-tools:$FABRIC_VERSION "$@"
}

wait_for() {  # wait_for <description> <command...>
  local what="$1"; shift
  for _ in $(seq 1 40); do "$@" >/dev/null 2>&1 && return 0; sleep 2; done
  echo "Timed out waiting for $what" >&2; return 1
}

up() {
  if [ ! -d "$NET/organizations" ]; then
    echo "== Generating identities"
    tools cryptogen generate --config=/net/crypto-config.yaml --output=/net/organizations
  fi
  if [ ! -f "$NET/channel-artifacts/$CHANNEL.block" ]; then
    echo "== Building the channel genesis block"
    mkdir -p "$NET/channel-artifacts"
    TOOLS_CFG=/net tools configtxgen -profile PehchaanChannel -channelID $CHANNEL \
      -outputBlock /net/channel-artifacts/$CHANNEL.block
  fi

  echo "== Starting orderer and peer"
  compose up -d

  if ! tools osnadmin channel list -o $ORDERER:7053 --ca-file $ORDERER_TLS/ca.crt \
        --client-cert $ORDERER_TLS/server.crt --client-key $ORDERER_TLS/server.key 2>/dev/null | grep -q "\"$CHANNEL\""; then
    echo "== Joining the orderer to channel '$CHANNEL'"
    wait_for "the orderer admin endpoint" tools osnadmin channel list -o $ORDERER:7053 \
      --ca-file $ORDERER_TLS/ca.crt --client-cert $ORDERER_TLS/server.crt --client-key $ORDERER_TLS/server.key
    tools osnadmin channel join --channelID $CHANNEL --config-block /net/channel-artifacts/$CHANNEL.block \
      -o $ORDERER:7053 --ca-file $ORDERER_TLS/ca.crt \
      --client-cert $ORDERER_TLS/server.crt --client-key $ORDERER_TLS/server.key
  fi

  if ! tools peer channel list 2>/dev/null | grep -qx "$CHANNEL"; then
    echo "== Joining the peer to channel '$CHANNEL'"
    wait_for "the peer" tools peer channel list
    for _ in $(seq 1 15); do
      tools peer channel join -b /net/channel-artifacts/$CHANNEL.block && break
      sleep 3
    done
  fi

  deploy
  status
}

deploy() {
  if tools peer lifecycle chaincode querycommitted --channelID $CHANNEL --name $CC_NAME 2>/dev/null \
      | grep -q "Version: $CC_VERSION, Sequence: $CC_SEQUENCE"; then
    echo "== Chaincode $CC_NAME $CC_VERSION (sequence $CC_SEQUENCE) is already committed"
    return
  fi
  echo "== Fetching chaincode dependencies (vendored so the build needs no network)"
  docker run --rm -v "$CC_SRC:/cc" -w /cc -e GOFLAGS=-buildvcs=false \
    hyperledger/fabric-ccenv:$FABRIC_VERSION sh -c "go mod tidy && go mod vendor"

  echo "== Packaging and installing chaincode $CC_NAME $CC_VERSION"
  local label="${CC_NAME}_${CC_VERSION}"
  tools peer lifecycle chaincode package /net/channel-artifacts/$label.tar.gz --path /cc --lang golang --label "$label"
  tools peer lifecycle chaincode install /net/channel-artifacts/$label.tar.gz || true   # "already installed" is fine
  local package_id
  package_id=$(tools peer lifecycle chaincode queryinstalled | sed -n "s/^Package ID: \(${label}:[0-9a-f]*\), Label.*/\1/p" | head -1)
  [ -n "$package_id" ] || { echo "Chaincode package was not installed" >&2; exit 1; }

  local orderer_args=(-o $ORDERER:7050 --tls --cafile $ORDERER_TLS/ca.crt)
  echo "== Approving and committing ($package_id)"
  tools peer lifecycle chaincode approveformyorg "${orderer_args[@]}" --channelID $CHANNEL --name $CC_NAME \
    --version "$CC_VERSION" --package-id "$package_id" --sequence "$CC_SEQUENCE"
  tools peer lifecycle chaincode commit "${orderer_args[@]}" --channelID $CHANNEL --name $CC_NAME \
    --version "$CC_VERSION" --sequence "$CC_SEQUENCE" \
    --peerAddresses $PEER:7051 --tlsRootCertFiles $PEER_ORG/peers/$PEER/tls/ca.crt
}

status() {
  echo "== Containers"
  docker ps --filter "network=$DOCKER_NET" --format '  {{.Names}}  {{.Status}}'
  echo "== Channel"
  tools peer channel getinfo -c $CHANNEL 2>/dev/null | sed 's/^/  /' || echo "  peer has not joined '$CHANNEL'"
  echo "== Chaincode"
  tools peer lifecycle chaincode querycommitted --channelID $CHANNEL 2>/dev/null | sed 's/^/  /' || true
}

case "${1:-}" in
  up) up ;;
  deploy) deploy ;;
  status) status ;;
  down) compose down ;;
  destroy)
    compose down --volumes
    docker ps -aq --filter "name=dev-$PEER" | xargs -r docker rm -f
    docker images -q "dev-$PEER*" | xargs -r docker rmi -f
    rm -rf "$NET/organizations" "$NET/channel-artifacts" "$CC_SRC/vendor"
    ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
