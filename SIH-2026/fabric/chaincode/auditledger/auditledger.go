// Package main is the PEHCHAAN audit-ledger chaincode.
//
// The gateway seals screening records into batches and computes a Merkle
// root over their hashes. This chaincode stores each batch's root on the
// Fabric ledger. No personal data goes on chain: only the root, counts,
// the first and last record ids and the gateway's Ed25519 signature.
//
// An anchor can be written once. Re-anchoring a batch id with any content is
// rejected, so a database administrator who rewrites sealed records cannot
// also rewrite what the ledger says the root was.
package main

import (
	"encoding/json"
	"fmt"
	"regexp"
	"time"

	"github.com/hyperledger/fabric-contract-api-go/v2/contractapi"
)

// AuditLedger is the contract.
type AuditLedger struct {
	contractapi.Contract
}

// BatchAnchor is what the ledger records for one sealed batch.
type BatchAnchor struct {
	Source      string `json:"source"`      // deployment that sealed the batch
	BatchID     string `json:"batchId"`     // batch number in that deployment
	MerkleRoot  string `json:"merkleRoot"`  // SHA-256 Merkle root over the batch's record hashes
	LeafCount   int    `json:"leafCount"`   // records in the batch
	FirstScan   string `json:"firstScan"`   // first record id
	LastScan    string `json:"lastScan"`    // last record id
	Signature   string `json:"signature"`   // gateway's Ed25519 signature over the batch message
	SubmittedBy string `json:"submittedBy"` // MSP of the submitting identity
	TxID        string `json:"txId"`
	AnchoredAt  string `json:"anchoredAt"` // transaction timestamp, UTC
}

var (
	rootPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)
	idPattern   = regexp.MustCompile(`^[A-Za-z0-9._-]{1,64}$`)
)

func key(source, batchID string) string {
	return "batch:" + source + ":" + batchID
}

// AnchorBatch records a batch root. It fails if that batch is already anchored.
func (c *AuditLedger) AnchorBatch(ctx contractapi.TransactionContextInterface,
	source, batchID, merkleRoot string, leafCount int, firstScan, lastScan, signature string) (*BatchAnchor, error) {
	if !idPattern.MatchString(source) || !idPattern.MatchString(batchID) {
		return nil, fmt.Errorf("source and batch id must be 1-64 characters of A-Z a-z 0-9 . _ -")
	}
	if !rootPattern.MatchString(merkleRoot) {
		return nil, fmt.Errorf("merkle root must be 64 lowercase hex characters")
	}
	if leafCount < 1 {
		return nil, fmt.Errorf("a batch holds at least one record")
	}
	if len(firstScan) > 128 || len(lastScan) > 128 || len(signature) > 512 {
		return nil, fmt.Errorf("field too long")
	}

	stub := ctx.GetStub()
	existing, err := stub.GetState(key(source, batchID))
	if err != nil {
		return nil, fmt.Errorf("reading ledger: %w", err)
	}
	if existing != nil {
		return nil, fmt.Errorf("batch %s of %s is already anchored and cannot be changed", batchID, source)
	}

	msp, err := ctx.GetClientIdentity().GetMSPID()
	if err != nil {
		return nil, fmt.Errorf("reading submitter identity: %w", err)
	}
	ts, err := stub.GetTxTimestamp()
	if err != nil {
		return nil, fmt.Errorf("reading transaction time: %w", err)
	}
	anchor := &BatchAnchor{
		Source: source, BatchID: batchID, MerkleRoot: merkleRoot, LeafCount: leafCount,
		FirstScan: firstScan, LastScan: lastScan, Signature: signature,
		SubmittedBy: msp, TxID: stub.GetTxID(),
		AnchoredAt: time.Unix(ts.Seconds, int64(ts.Nanos)).UTC().Format(time.RFC3339),
	}
	data, err := json.Marshal(anchor)
	if err != nil {
		return nil, err
	}
	if err := stub.PutState(key(source, batchID), data); err != nil {
		return nil, fmt.Errorf("writing ledger: %w", err)
	}
	if err := stub.SetEvent("BatchAnchored", data); err != nil {
		return nil, err
	}
	return anchor, nil
}

// GetBatch returns the anchor of one batch.
func (c *AuditLedger) GetBatch(ctx contractapi.TransactionContextInterface, source, batchID string) (*BatchAnchor, error) {
	data, err := ctx.GetStub().GetState(key(source, batchID))
	if err != nil {
		return nil, fmt.Errorf("reading ledger: %w", err)
	}
	if data == nil {
		return nil, fmt.Errorf("batch %s of %s is not anchored", batchID, source)
	}
	var anchor BatchAnchor
	if err := json.Unmarshal(data, &anchor); err != nil {
		return nil, err
	}
	return &anchor, nil
}

// VerifyRoot says whether the ledger holds exactly this root for the batch.
func (c *AuditLedger) VerifyRoot(ctx contractapi.TransactionContextInterface, source, batchID, merkleRoot string) (bool, error) {
	anchor, err := c.GetBatch(ctx, source, batchID)
	if err != nil {
		return false, err
	}
	return anchor.MerkleRoot == merkleRoot, nil
}

// ListBatches returns every anchor of one deployment, in key order.
func (c *AuditLedger) ListBatches(ctx contractapi.TransactionContextInterface, source string) ([]*BatchAnchor, error) {
	if !idPattern.MatchString(source) {
		return nil, fmt.Errorf("invalid source")
	}
	prefix := "batch:" + source + ":"
	it, err := ctx.GetStub().GetStateByRange(prefix, prefix+"￿")
	if err != nil {
		return nil, fmt.Errorf("reading ledger: %w", err)
	}
	defer it.Close()
	anchors := []*BatchAnchor{}
	for it.HasNext() {
		kv, err := it.Next()
		if err != nil {
			return nil, err
		}
		var anchor BatchAnchor
		if err := json.Unmarshal(kv.Value, &anchor); err != nil {
			return nil, err
		}
		anchors = append(anchors, &anchor)
	}
	return anchors, nil
}

func main() {
	cc, err := contractapi.NewChaincode(&AuditLedger{})
	if err != nil {
		panic(fmt.Sprintf("creating auditledger chaincode: %v", err))
	}
	if err := cc.Start(); err != nil {
		panic(fmt.Sprintf("starting auditledger chaincode: %v", err))
	}
}
