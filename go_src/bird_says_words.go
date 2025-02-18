package main

import (
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"os"
	"sort"

	"github.com/BurntSushi/toml"
	"github.com/twilio/twilio-go"
	twilioApi "github.com/twilio/twilio-go/rest/api/v2010"
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

func getShuffledKeys(birdDb map[string]BirdWord, path string) ([]string, error) {
	keys := make([]string, 0, len(birdDb))
	for k := range birdDb {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	data, err := os.ReadFile(path)
	if err != nil {
		if !os.IsNotExist(err) {
			return nil, fmt.Errorf("reading shuffled keys: %w", err)
		}
		// Create new shuffled keys if file doesn't exist
		rand.Shuffle(len(keys), func(i, j int) { keys[i], keys[j] = keys[j], keys[i] })
		data, err := json.Marshal(keys)
		if err != nil {
			return nil, fmt.Errorf("marshalling shuffled keys: %w", err)
		}
		err = os.WriteFile(path, data, 0644)
		if err != nil {
			return nil, fmt.Errorf("writing shuffled keys: %w", err)
		}
		return keys, nil
	}

	if err := json.Unmarshal(data, &keys); err != nil {
		return nil, fmt.Errorf("parsing shuffled keys: %w", err)
	}
	return keys, nil
}

func sendBirdMessage(client *twilio.RestClient, twilioNumber string, phoneNumber string, birdWord BirdWord) error {
	params := &twilioApi.CreateMessageParams{}
	params.SetTo(phoneNumber)
	params.SetFrom(twilioNumber)
	params.SetBody(fmt.Sprintf("%s\n%s", birdWord.Text, birdWord.Url))
	params.SetMediaUrl([]string{birdWord.Img})

	_, err := client.Api.CreateMessage(params)
	return err
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

	keys, err := getShuffledKeys(birdDb, "shuffled_keys.json")
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
		birdName := keys[messageTracker.Index[phoneNumber]]
		birdWord := birdDb[birdName]
		fmt.Printf("Sending message to %s: %s\n%s\n", phoneNumber, birdName, birdWord.Text[:20])

		if err := sendBirdMessage(client, config.Twilio.Number, phoneNumber, birdWord); err != nil {
			log.Printf("Failed to send message to %s: %v", phoneNumber, err)
			continue
		}

		messageTracker.Index[phoneNumber]++
	}
	if err := messageTracker.save(); err != nil {
		log.Fatalf("Error saving message tracker: %v", err)
	}
}
