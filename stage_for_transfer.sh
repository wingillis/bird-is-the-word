set -e

FILE=$1

# check if file exists
if [ ! -f $FILE ]; then
    echo "File not found!"
    exit 1
fi

cp $FILE ./bird_db.json
echo "JSON file copied to bird_db.json"

GOOS=linux GOARCH=arm64 go build -ldflags "-w -s" -o bird_says_words_arm64 go_src/bird_says_words.go
echo "Compiled for ARM64"

go build -ldflags "-w -s" -o bird_says_words go_src/bird_says_words.go