package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math/rand"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/BurntSushi/toml"
	"github.com/twilio/twilio-go"
	twilioApi "github.com/twilio/twilio-go/rest/api/v2010"
)

const (
	defaultMaxVideoBytes        int64 = 4500000
	defaultVideoHeadTimeoutSecs       = 5
)

type Config struct {
	Twilio struct {
		Sid    string `toml:"sid"`
		Auth   string `toml:"auth"`
		Number string `toml:"number"`
	} `toml:"twilio"`
	PhoneNumbers []string `toml:"numbers"`
}

type BirdWord struct {
	Img  string `json:"img_url"`
	Text string `json:"fact"`
	Url  string `json:"species_page"`
}

type MessageTracker struct {
	Index map[string]int
	path  string
}

func getEnv(key, fallback string) string {
	if value, exists := os.LookupEnv(key); exists {
		return value
	}
	return fallback
}

func getEnvInt64(key string, fallback int64) int64 {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseInt(value, 10, 64)
	if err != nil || parsed <= 0 {
		log.Printf("Invalid %s=%q; using %d", key, value, fallback)
		return fallback
	}
	return parsed
}

func getEnvDurationSeconds(key string, fallbackSeconds int) time.Duration {
	value := os.Getenv(key)
	if value == "" {
		return time.Duration(fallbackSeconds) * time.Second
	}
	parsed, err := strconv.Atoi(value)
	if err != nil || parsed <= 0 {
		log.Printf("Invalid %s=%q; using %ds", key, value, fallbackSeconds)
		return time.Duration(fallbackSeconds) * time.Second
	}
	return time.Duration(parsed) * time.Second
}

func (mt *MessageTracker) save() error {
	data, err := json.Marshal(mt.Index)
	if err != nil {
		return fmt.Errorf("error marshalling message index: %w", err)
	}
	return os.WriteFile(mt.path, data, 0644)
}

func NewMessageTracker(path string) (*MessageTracker, error) {
	mt := &MessageTracker{
		Index: make(map[string]int),
		path:  path,
	}
	data, err := os.ReadFile(path)
	if err != nil {
		if !os.IsNotExist(err) {
			return nil, fmt.Errorf("error reading message index: %w", err)
		}
		return mt, mt.save() // save file if it doesn't exist
	}
	if err := json.Unmarshal(data, &mt.Index); err != nil {
		return nil, fmt.Errorf("error parsing message index: %w", err)
	}
	return mt, nil
}

func loadConfig(path string) (*Config, error) {
	var config Config
	if _, err := toml.DecodeFile(path, &config); err != nil {
		return nil, err
	}
	return &config, nil
}

func loadBirdDB(path string) (map[string]BirdWord, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("error reading bird_db.json: %w", err)
	}

	var birdDb map[string]BirdWord
	if err := json.Unmarshal(data, &birdDb); err != nil {
		return nil, fmt.Errorf("error parsing bird_db.json: %w", err)
	}
	return birdDb, nil
}

func loadVideoManifest(path string) (map[string]string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("error reading video manifest: %w", err)
	}

	var videoUrls map[string]string
	if err := json.Unmarshal(data, &videoUrls); err != nil {
		return nil, fmt.Errorf("error parsing video manifest: %w", err)
	}
	return videoUrls, nil
}

func normalizeBirdVideoName(name string) string {
	name = strings.ReplaceAll(name, "'s", "_s")
	name = strings.ReplaceAll(name, " ", "_")
	name = strings.ReplaceAll(name, "'", "")
	return name
}

func videoURLForBird(videoManifest map[string]string, birdName string) (string, bool) {
	if videoURL, ok := videoManifest[birdName]; ok {
		return videoURL, true
	}
	videoURL, ok := videoManifest[normalizeBirdVideoName(birdName)]
	return videoURL, ok
}

func filterEligibleBirdsByLocalVideos(
	birdDb map[string]BirdWord,
	baseURL string,
	videoDir string,
	maxVideoBytes int64,
) (map[string]BirdWord, map[string]string, error) {
	eligibleBirds := make(map[string]BirdWord)
	eligibleVideos := make(map[string]string)

	birdNames := make([]string, 0, len(birdDb))
	for birdName := range birdDb {
		birdNames = append(birdNames, birdName)
	}
	sort.Strings(birdNames)

	for _, birdName := range birdNames {
		videoName := normalizeBirdVideoName(birdName) + ".mp4"
		videoPath := filepath.Join(videoDir, videoName)
		info, err := os.Stat(videoPath)
		if err != nil {
			if !os.IsNotExist(err) {
				log.Printf("Skipping %s video %q: %v", birdName, videoPath, err)
			}
			continue
		}
		if info.IsDir() {
			continue
		}
		if info.Size() > maxVideoBytes {
			log.Printf("Skipping %s video %q: video is %d bytes, exceeding limit %d", birdName, videoPath, info.Size(), maxVideoBytes)
			continue
		}

		videoURL, err := url.JoinPath(baseURL, videoName)
		if err != nil {
			return nil, nil, fmt.Errorf("building video URL for %s: %w", birdName, err)
		}
		eligibleBirds[birdName] = birdDb[birdName]
		eligibleVideos[birdName] = videoURL
	}

	return eligibleBirds, eligibleVideos, nil
}

func validateVideoURL(ctx context.Context, client *http.Client, rawURL string, maxBytes int64, allowHTTP bool) error {
	parsedURL, err := url.Parse(rawURL)
	if err != nil {
		return fmt.Errorf("invalid URL: %w", err)
	}
	if parsedURL.Scheme != "https" && !(allowHTTP && parsedURL.Scheme == "http") {
		return fmt.Errorf("video URL must use HTTPS")
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodHead, rawURL, nil)
	if err != nil {
		return fmt.Errorf("building HEAD request: %w", err)
	}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("HEAD request failed: %w", err)
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body)

	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return fmt.Errorf("HEAD returned status %d", resp.StatusCode)
	}
	contentType := strings.ToLower(strings.TrimSpace(strings.Split(resp.Header.Get("Content-Type"), ";")[0]))
	if contentType != "video/mp4" {
		return fmt.Errorf("Content-Type must be video/mp4, got %q", resp.Header.Get("Content-Type"))
	}
	if resp.ContentLength < 0 {
		return fmt.Errorf("Content-Length is required")
	}
	if resp.ContentLength > maxBytes {
		return fmt.Errorf("video is %d bytes, exceeding limit %d", resp.ContentLength, maxBytes)
	}
	return nil
}

func filterEligibleBirds(
	birdDb map[string]BirdWord,
	videoManifest map[string]string,
	client *http.Client,
	maxVideoBytes int64,
	headTimeout time.Duration,
	allowHTTP bool,
) (map[string]BirdWord, map[string]string) {
	eligibleBirds := make(map[string]BirdWord)
	eligibleVideos := make(map[string]string)

	birdNames := make([]string, 0, len(birdDb))
	for birdName := range birdDb {
		birdNames = append(birdNames, birdName)
	}
	sort.Strings(birdNames)

	for _, birdName := range birdNames {
		videoURL, ok := videoURLForBird(videoManifest, birdName)
		if !ok {
			continue
		}

		ctx, cancel := context.WithTimeout(context.Background(), headTimeout)
		err := validateVideoURL(ctx, client, videoURL, maxVideoBytes, allowHTTP)
		cancel()
		if err != nil {
			log.Printf("Skipping %s video %q: %v", birdName, videoURL, err)
			continue
		}

		eligibleBirds[birdName] = birdDb[birdName]
		eligibleVideos[birdName] = videoURL
	}

	return eligibleBirds, eligibleVideos
}

func sameStringSet(a []string, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	aCopy := append([]string(nil), a...)
	bCopy := append([]string(nil), b...)
	sort.Strings(aCopy)
	sort.Strings(bCopy)
	for i := range aCopy {
		if aCopy[i] != bCopy[i] {
			return false
		}
	}
	return true
}

func shuffledKeysFromBirdDB(birdDb map[string]BirdWord) []string {
	keys := make([]string, 0, len(birdDb))
	for k := range birdDb {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

func saveShuffledKeys(path string, keys []string) error {
	shuffled := append([]string(nil), keys...)
	rand.Shuffle(len(shuffled), func(i, j int) { shuffled[i], shuffled[j] = shuffled[j], shuffled[i] })
	data, err := json.Marshal(shuffled)
	if err != nil {
		return fmt.Errorf("marshalling shuffled keys: %w", err)
	}
	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("writing shuffled keys: %w", err)
	}
	return nil
}

func getShuffledKeys(birdDb map[string]BirdWord, path string) ([]string, error) {
	keys := shuffledKeysFromBirdDB(birdDb)

	data, err := os.ReadFile(path)
	if err != nil {
		if !os.IsNotExist(err) {
			return nil, fmt.Errorf("reading shuffled keys: %w", err)
		}
		if err := saveShuffledKeys(path, keys); err != nil {
			return nil, err
		}
		return getShuffledKeys(birdDb, path)
	}

	var shuffledKeys []string
	if err := json.Unmarshal(data, &shuffledKeys); err != nil {
		return nil, fmt.Errorf("parsing shuffled keys: %w", err)
	}
	if !sameStringSet(shuffledKeys, keys) {
		log.Printf("Regenerating %s because eligible birds changed", path)
		if err := saveShuffledKeys(path, keys); err != nil {
			return nil, err
		}
		return getShuffledKeys(birdDb, path)
	}
	return shuffledKeys, nil
}

func sendBirdMessage(client *twilio.RestClient, twilioNumber string, phoneNumber string, birdWord BirdWord, videoURL string) error {
	params := &twilioApi.CreateMessageParams{}
	params.SetTo(phoneNumber)
	params.SetFrom(twilioNumber)
	params.SetBody(fmt.Sprintf("%s\n%s", birdWord.Text, birdWord.Url))
	params.SetMediaUrl([]string{videoURL})
	// params.SetMediaUrl([]string{birdWord.Img, videoURL})

	_, err := client.Api.CreateMessage(params)
	return err
}

func previewText(text string, maxLength int) string {
	if len(text) <= maxLength {
		return text
	}
	return text[:maxLength]
}

func main() {
	// this file must exist
	config_path := getEnv("BIRD_CONFIG_PATH", "config.toml")
	config, err := loadConfig(config_path)
	if err != nil {
		log.Fatalf("Error reading config.toml: %v", err)
	}

	// this file must exist too
	bird_db_path := getEnv("BIRD_DB_PATH", "bird_db.json")
	birdDb, err := loadBirdDB(bird_db_path)
	if err != nil {
		log.Fatalf("Error reading bird_db.json: %v", err)
	}

	maxVideoBytes := getEnvInt64("BIRD_MAX_VIDEO_BYTES", defaultMaxVideoBytes)
	headTimeout := getEnvDurationSeconds("BIRD_VIDEO_HEAD_TIMEOUT_SECONDS", defaultVideoHeadTimeoutSecs)
	videoSource := "bird_video_urls.json"
	eligibleBirds := make(map[string]BirdWord)
	eligibleVideos := make(map[string]string)
	videoBaseURL := os.Getenv("BIRD_VIDEO_BASE_URL")
	if videoBaseURL != "" {
		videoDir := getEnv("BIRD_VIDEO_DIR", "bird_videos")
		eligibleBirds, eligibleVideos, err = filterEligibleBirdsByLocalVideos(birdDb, videoBaseURL, videoDir, maxVideoBytes)
		if err != nil {
			log.Fatalf("Error checking local videos: %v", err)
		}
		videoSource = videoDir
	} else {
		videoManifestPath := getEnv("BIRD_VIDEO_URLS_PATH", "bird_video_urls.json")
		videoManifest, err := loadVideoManifest(videoManifestPath)
		if err != nil {
			log.Fatalf("Error reading video manifest: %v", err)
		}
		eligibleBirds, eligibleVideos = filterEligibleBirds(
			birdDb,
			videoManifest,
			&http.Client{},
			maxVideoBytes,
			headTimeout,
			false,
		)
		videoSource = videoManifestPath
	}
	if len(eligibleBirds) == 0 {
		log.Fatalf("No eligible birds have usable videos from %s", videoSource)
	}
	log.Printf("Loaded %d bird facts; %d have valid video URLs", len(birdDb), len(eligibleBirds))

	keys, err := getShuffledKeys(eligibleBirds, "shuffled_keys.json")
	if err != nil {
		log.Fatalf("Error getting shuffled keys: %v", err)
	}

	// store the key each phone number is on
	messageTracker, err := NewMessageTracker("message_index.json")
	if err != nil {
		log.Fatalf("Error loading message tracker: %v", err)
	}

	client := twilio.NewRestClientWithParams(twilio.ClientParams{
		Username: config.Twilio.Sid,
		Password: config.Twilio.Auth,
	})

	for _, phoneNumber := range config.PhoneNumbers {
		birdName := keys[messageTracker.Index[phoneNumber]%len(keys)]
		birdWord := eligibleBirds[birdName]
		videoURL := eligibleVideos[birdName]
		fmt.Printf("Sending message to %s: %s\n%s\n", phoneNumber, birdName, previewText(birdWord.Text, 20))

		if err := sendBirdMessage(client, config.Twilio.Number, phoneNumber, birdWord, videoURL); err != nil {
			log.Printf("Failed to send message to %s: %v", phoneNumber, err)
			continue
		}

		messageTracker.Index[phoneNumber]++
	}
	if err := messageTracker.save(); err != nil {
		log.Fatalf("Error saving message tracker: %v", err)
	}
}
