package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"testing"
	"time"
)

func TestNormalizeBirdVideoName(t *testing.T) {
	tests := map[string]string{
		"Lowland Akalat":            "Lowland_Akalat",
		"Cabanis's Ground-Sparrow":  "Cabanis_s_Ground-Sparrow",
		"Goldie's Lorikeet":         "Goldie_s_Lorikeet",
		"White's Thrush":            "White_s_Thrush",
		"Black-bellied Starling":    "Black-bellied_Starling",
		"Yellow-throated 'Warbler'": "Yellow-throated_Warbler",
	}

	for input, expected := range tests {
		if got := normalizeBirdVideoName(input); got != expected {
			t.Fatalf("normalizeBirdVideoName(%q) = %q, want %q", input, got, expected)
		}
	}
}

func TestVideoURLForBirdUsesExactThenNormalizedManifestKeys(t *testing.T) {
	manifest := map[string]string{
		"Lowland Akalat":           "https://example.test/exact.mp4",
		"Cabanis_s_Ground-Sparrow": "https://example.test/normalized.mp4",
	}

	if got, ok := videoURLForBird(manifest, "Lowland Akalat"); !ok || got != "https://example.test/exact.mp4" {
		t.Fatalf("exact manifest lookup = %q, %v", got, ok)
	}
	if got, ok := videoURLForBird(manifest, "Cabanis's Ground-Sparrow"); !ok || got != "https://example.test/normalized.mp4" {
		t.Fatalf("normalized manifest lookup = %q, %v", got, ok)
	}
	if _, ok := videoURLForBird(manifest, "Missing Bird"); ok {
		t.Fatal("missing bird unexpectedly had a video URL")
	}
}

func TestFilterEligibleBirds(t *testing.T) {
	server := newVideoServer("video/mp4", 1234, http.StatusOK)
	defer server.Close()

	birdDb := map[string]BirdWord{
		"Lowland Akalat":           {Text: "fact", Img: "https://example.test/image.jpg", Url: "https://example.test/bird"},
		"Cabanis's Ground-Sparrow": {Text: "fact", Img: "https://example.test/image.jpg", Url: "https://example.test/bird"},
		"Missing Video":            {Text: "fact", Img: "https://example.test/image.jpg", Url: "https://example.test/bird"},
	}
	manifest := map[string]string{
		"Lowland Akalat":           server.URL + "/lowland.mp4",
		"Cabanis_s_Ground-Sparrow": server.URL + "/cabanis.mp4",
	}

	eligibleBirds, eligibleVideos := filterEligibleBirds(
		birdDb,
		manifest,
		server.Client(),
		4500000,
		time.Second,
		true,
	)

	if len(eligibleBirds) != 2 {
		t.Fatalf("eligibleBirds length = %d, want 2", len(eligibleBirds))
	}
	if eligibleVideos["Lowland Akalat"] == "" {
		t.Fatal("Lowland Akalat did not keep its video URL")
	}
	if eligibleVideos["Cabanis's Ground-Sparrow"] == "" {
		t.Fatal("normalized manifest key did not match Cabanis's Ground-Sparrow")
	}
	if _, ok := eligibleBirds["Missing Video"]; ok {
		t.Fatal("bird without video URL was eligible")
	}
}

func TestFilterEligibleBirdsByLocalVideos(t *testing.T) {
	tempDir := t.TempDir()
	writeBytes(t, filepath.Join(tempDir, "Lowland_Akalat.mp4"), 1234)
	writeBytes(t, filepath.Join(tempDir, "Cabanis_s_Ground-Sparrow.mp4"), 1234)
	writeBytes(t, filepath.Join(tempDir, "Oversized_Bird.mp4"), 5001)

	birdDb := map[string]BirdWord{
		"Lowland Akalat":           {Text: "fact"},
		"Cabanis's Ground-Sparrow": {Text: "fact"},
		"Missing Video":            {Text: "fact"},
		"Oversized Bird":           {Text: "fact"},
	}

	eligibleBirds, eligibleVideos, err := filterEligibleBirdsByLocalVideos(
		birdDb,
		"https://example.test/bird-videos/",
		tempDir,
		5000,
	)
	if err != nil {
		t.Fatalf("filterEligibleBirdsByLocalVideos returned error: %v", err)
	}

	if len(eligibleBirds) != 2 {
		t.Fatalf("eligibleBirds length = %d, want 2", len(eligibleBirds))
	}
	if got := eligibleVideos["Lowland Akalat"]; got != "https://example.test/bird-videos/Lowland_Akalat.mp4" {
		t.Fatalf("Lowland Akalat URL = %q", got)
	}
	if got := eligibleVideos["Cabanis's Ground-Sparrow"]; got != "https://example.test/bird-videos/Cabanis_s_Ground-Sparrow.mp4" {
		t.Fatalf("Cabanis's Ground-Sparrow URL = %q", got)
	}
	if _, ok := eligibleBirds["Missing Video"]; ok {
		t.Fatal("bird without a local video was eligible")
	}
	if _, ok := eligibleBirds["Oversized Bird"]; ok {
		t.Fatal("bird with oversized local video was eligible")
	}
}

func TestGetShuffledKeysRegeneratesWhenEligibleSetChanges(t *testing.T) {
	tempDir := t.TempDir()
	path := filepath.Join(tempDir, "shuffled_keys.json")
	initialKeys := []string{"Old Bird", "Lowland Akalat"}
	writeJSON(t, path, initialKeys)

	birdDb := map[string]BirdWord{
		"Lowland Akalat": {Text: "fact"},
		"New Bird":       {Text: "fact"},
	}

	keys, err := getShuffledKeys(birdDb, path)
	if err != nil {
		t.Fatalf("getShuffledKeys returned error: %v", err)
	}
	if !sameStringSet(keys, []string{"Lowland Akalat", "New Bird"}) {
		t.Fatalf("keys = %#v, want Lowland Akalat and New Bird", keys)
	}

	var saved []string
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("reading saved keys: %v", err)
	}
	if err := json.Unmarshal(data, &saved); err != nil {
		t.Fatalf("parsing saved keys: %v", err)
	}
	if !sameStringSet(saved, []string{"Lowland Akalat", "New Bird"}) {
		t.Fatalf("saved keys = %#v, want regenerated eligible set", saved)
	}
}

func TestValidateVideoURL(t *testing.T) {
	tests := []struct {
		name        string
		contentType string
		size        int64
		status      int
		maxBytes    int64
		wantErr     bool
	}{
		{name: "valid mp4", contentType: "video/mp4", size: 1234, status: http.StatusOK, maxBytes: 4500000},
		{name: "valid mp4 with params", contentType: "video/mp4; charset=binary", size: 1234, status: http.StatusOK, maxBytes: 4500000},
		{name: "wrong content type", contentType: "video/quicktime", size: 1234, status: http.StatusOK, maxBytes: 4500000, wantErr: true},
		{name: "oversized", contentType: "video/mp4", size: 5000, status: http.StatusOK, maxBytes: 4999, wantErr: true},
		{name: "bad status", contentType: "video/mp4", size: 1234, status: http.StatusNotFound, maxBytes: 4500000, wantErr: true},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			server := newVideoServer(tc.contentType, tc.size, tc.status)
			defer server.Close()

			err := validateVideoURL(contextWithTestTimeout(t), server.Client(), server.URL+"/bird.mp4", tc.maxBytes, true)
			if tc.wantErr && err == nil {
				t.Fatal("validateVideoURL returned nil error, want error")
			}
			if !tc.wantErr && err != nil {
				t.Fatalf("validateVideoURL returned error: %v", err)
			}
		})
	}
}

func TestValidateVideoURLRejectsPlainHTTPUnlessAllowed(t *testing.T) {
	server := newPlainVideoServer("video/mp4", 1234, http.StatusOK)
	defer server.Close()

	if err := validateVideoURL(contextWithTestTimeout(t), server.Client(), server.URL+"/bird.mp4", 4500000, false); err == nil {
		t.Fatal("validateVideoURL accepted plain HTTP without allowHTTP")
	}
}

func TestValidateVideoURLRejectsMissingContentLength(t *testing.T) {
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "video/mp4")
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	client := server.Client()

	if err := validateVideoURL(contextWithTestTimeout(t), client, server.URL+"/bird.mp4", 4500000, false); err == nil {
		t.Fatal("validateVideoURL accepted a response without Content-Length")
	}
}

func newVideoServer(contentType string, size int64, status int) *httptest.Server {
	return httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", contentType)
		w.Header().Set("Content-Length", strconv.FormatInt(size, 10))
		w.WriteHeader(status)
	}))
}

func newPlainVideoServer(contentType string, size int64, status int) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", contentType)
		w.Header().Set("Content-Length", strconv.FormatInt(size, 10))
		w.WriteHeader(status)
	}))
}

func contextWithTestTimeout(t *testing.T) context.Context {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	t.Cleanup(cancel)
	return ctx
}

func writeJSON(t *testing.T, path string, value any) {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatalf("marshalling JSON: %v", err)
	}
	if err := os.WriteFile(path, data, 0644); err != nil {
		t.Fatalf("writing JSON: %v", err)
	}
}

func writeBytes(t *testing.T, path string, size int64) {
	t.Helper()
	file, err := os.Create(path)
	if err != nil {
		t.Fatalf("creating %s: %v", path, err)
	}
	defer file.Close()
	if err := file.Truncate(size); err != nil {
		t.Fatalf("truncating %s: %v", path, err)
	}
}
