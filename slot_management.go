package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/google/shlex"
)

// SlotActionRequest represents the request body for slot actions
type SlotActionRequest struct {
	Action     string `json:"action"`     // "restore" or "save"
	Filename   string `json:"filename"`   // "${slot}.bin"
	SlotID     int    `json:"id_slot"`    // Slot identifier
}

// SlotActionResponse represents the response for slot actions
type SlotActionResponse struct {
	Success    bool   `json:"success"`
	Message    string `json:"message,omitempty"`
	SlotID     int    `json:"id_slot"`
	Filename   string `json:"filename"`
}

// slotParseResult holds the result of parsing slot arguments
type slotParseResult struct {
	hasParallel     bool
	hasSlots        bool
	hasSlotSavePath bool
	slotSavePath    string
	numSlots        int
	err             error
}

// initSlotManagementClient initializes the HTTP client for slot management API calls
func initSlotManagementClient() {
	slotManagementClient = &http.Client{
		Timeout: 30 * time.Second,
		Transport: &http.Transport{
			MaxIdleConns:        10,
			MaxIdleConnsPerHost: 10,
			IdleConnTimeout:     90 * time.Second,
		},
	}
}

// parseSlotArgs extracts slot configuration from service arguments
func parseSlotArgs(argsStr string) slotParseResult {
	args, err := shlex.Split(argsStr)
	if err != nil {
		return slotParseResult{err: err}
	}

	result := slotParseResult{}
	hasParallel := false
	hasSlots := false
	hasSlotSavePath := false
	var slotSavePath string

	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--parallel":
			hasParallel = true
			if i+1 >= len(args) {
				return slotParseResult{err: fmt.Errorf("--parallel argument missing value")}
			}
			numStr := args[i+1]
			num, err := strconv.Atoi(numStr)
			if err != nil {
				return slotParseResult{err: fmt.Errorf("invalid --parallel value %q: %w", numStr, err)}
			}
			result.numSlots = num
		case "--slots":
			hasSlots = true
		case "--slot-save-path":
			hasSlotSavePath = true
			if i+1 >= len(args) {
				return slotParseResult{err: fmt.Errorf("--slot-save-path argument missing value")}
			}
			slotSavePath = args[i+1]
		}
	}

	result.hasParallel = hasParallel
	result.hasSlots = hasSlots
	result.hasSlotSavePath = hasSlotSavePath
	result.slotSavePath = slotSavePath
	return result
}

// buildSlotFilename constructs the filename for a given slot ID
func buildSlotFilename(slotID int) string {
	return fmt.Sprintf("%d.bin", slotID)
}

// buildSlotFilePath constructs the full path to a slot file
func buildSlotFilePath(slotSavePath string, slotID int) string {
	return filepath.Join(slotSavePath, buildSlotFilename(slotID))
}

// manageSlots handles slot save/restore operations for a service
func manageSlots(service ServiceConfig, action string) {
	// Check if this is a llama-server with slots
	lowerCommand := strings.ToLower(service.Command)
	if !strings.Contains(lowerCommand, "llama-server") {
		return
	}

	// Validate and extract info in one call
	result := parseSlotArgs(service.Args)
	if result.err != nil || !result.hasParallel || !result.hasSlots || !result.hasSlotSavePath {
		return
	}

	slotSavePath := result.slotSavePath
	numSlots := result.numSlots

	log.Printf("[%s] %s %d slots from/to %s", service.Name, strings.Title(action), numSlots, slotSavePath)

	for slotID := 0; slotID < numSlots; slotID++ {
		var err error
		if action == "save" {
			err = saveSlot(service, slotID)
		} else {
			err = restoreSlot(service, slotID, slotSavePath)
		}
		if err != nil {
			log.Printf("[%s] Warning: Failed to %s slot %d: %v", service.Name, action, slotID, err)
			// Continue with rest of slots
		}
	}
}

// performSlotAction sends a slot action request to the service
func performSlotAction(serviceConfig ServiceConfig, slotID int, action string, filename string) (*SlotActionResponse, error) {
	// Construct URL based on action
	url := fmt.Sprintf("http://%s:%s/slots/%d?action=%s",
		serviceConfig.ProxyTargetHost,
		serviceConfig.ProxyTargetPort,
		slotID,
		action)

	// Create payload with action, slot ID, and filename
	payload := SlotActionRequest{
		Action:   action,
		SlotID:   slotID,
		Filename: filename,
	}

	// Log the request for debugging
	log.Printf("[%s] Slot %d %s request: action=%s, slot_id=%d, filename=%s",
		serviceConfig.Name, slotID, action, action, slotID, filename)

	// Marshal to JSON
	jsonPayload, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	// Send HTTP POST request
	resp, err := slotManagementClient.Post(url, "application/json", bytes.NewBuffer(jsonPayload))
	if err != nil {
		return nil, fmt.Errorf("failed to send %s request: %w", action, err)
	}
	defer resp.Body.Close()

	// Check response status
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("%s request failed with status %d: %s", action, resp.StatusCode, string(body))
	}

	// Decode response
	var respBody SlotActionResponse
	if err := json.NewDecoder(resp.Body).Decode(&respBody); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return &respBody, nil
}

// restoreSlot restores a slot from disk
func restoreSlot(serviceConfig ServiceConfig, slotID int, slotSavePath string) error {
	// Construct file path
	filePath := buildSlotFilePath(slotSavePath, slotID)

	// Extract directory path from file path
	dirPath := filepath.Dir(filePath)

	// Check if directory exists
	if _, err := os.Stat(dirPath); os.IsNotExist(err) {
		log.Printf("[WARNING] Slot directory does not exist: %s. Slot restore may fail if the directory is expected to be managed externally.", dirPath)
	} else if err != nil {
		return fmt.Errorf("failed to check slot directory %s: %w", dirPath, err)
	}

	// Check if file exists
	if _, err := os.Stat(filePath); os.IsNotExist(err) {
		return fmt.Errorf("slot file not found: %s", filePath)
	}

	// Build the filename for the restore request
	filename := buildSlotFilename(slotID)

	// Send restore request to service
	respBody, err := performSlotAction(serviceConfig, slotID, "restore", filename)
	if err != nil {
		return err
	}

	// Log success message with response data
	log.Printf("[%s] Slot %d restored successfully: %s", serviceConfig.Name, slotID, respBody.Message)
	return nil
}

// saveSlot saves a slot to disk
func saveSlot(serviceConfig ServiceConfig, slotID int) error {
	// Build the filename for the save request
	filename := buildSlotFilename(slotID)

	// Send save request to service
	respBody, err := performSlotAction(serviceConfig, slotID, "save", filename)
	if err != nil {
		return err
	}

	// Log success message with response data
	log.Printf("[%s] Slot %d saved successfully: %s", serviceConfig.Name, slotID, respBody.Message)
	return nil
}
