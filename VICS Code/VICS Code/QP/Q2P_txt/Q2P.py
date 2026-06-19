import re
import os
from collections import Counter

# Function to load words from a file
def load_words(file_path):
    """Load words from a file into a set for fast lookup."""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return set(file.read().splitlines())  # Read lines and strip newlines
    except FileNotFoundError:
        print(f"Warning: File not found - {file_path}")
        return set()

# Function to count word occurrences in a text
def count_words_in_text(text, words):
    """Count occurrences of words in text using regex and Counter."""
    word_pattern = re.compile(r'\b\w+\b', re.IGNORECASE)
    text_words = word_pattern.findall(text.lower())  # Tokenize text
    word_counts = Counter(text_words)  # Count occurrences of each word

    # Count each occurrence of the words in the set
    total_count = 0
    for word in words:
        count = word_counts[word.lower()]
        if count > 0:
            total_count += count
    return total_count

# Main function
def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_path = os.path.normpath(os.path.join(script_dir, '..', '..'))
    words_folder = script_dir

    # File paths
    Punish_words_file = os.path.join(words_folder, 'Punish.txt') #-3
    Threaten_words_file = os.path.join(words_folder, 'Threaten.txt') #-2
    Oppose_words_file = os.path.join(words_folder, 'Oppose-Resist.txt') #-1
    Neutral_words_file = os.path.join(words_folder, 'Neutral.txt') #0
    Appeal_words_file = os.path.join(words_folder, 'Appeal-Support.txt') #1
    Promise_words_file = os.path.join(words_folder, 'Promise.txt') #2
    Reward_words_file = os.path.join(words_folder, 'Reward.txt') #3

    input_text_file = os.path.join(base_path, 'input_text.txt')

    # Load words
    Punish_words = load_words(Punish_words_file)
    Threaten_words = load_words(Threaten_words_file)
    Oppose_words = load_words(Oppose_words_file)
    Neutral_words = load_words(Neutral_words_file)
    Appeal_words = load_words(Appeal_words_file)
    Promise_words = load_words(Promise_words_file)
    Reward_words = load_words(Reward_words_file)



    # Load input text
    try:
        with open(input_text_file, 'r', encoding='utf-8') as file:
            text = file.read()
    except FileNotFoundError:
        print(f"Error: Input text file not found - {input_text_file}")
        return

    # Count positive and negative words
    Punish_count = count_words_in_text(text, Punish_words)
    Threaten_count = count_words_in_text(text, Threaten_words)
    Oppose_count = count_words_in_text(text, Oppose_words)
    Neutral_count = count_words_in_text(text, Neutral_words)
    Appeal_count = count_words_in_text(text, Appeal_words)
    Promise_count = count_words_in_text(text, Promise_words)
    Reward_count = count_words_in_text(text, Reward_words)


    # Calculate Nature of Political Universe Index

    Punish_value= Punish_count*(-3)
    Threaten_value=Threaten_count*(-2)
    Oppose_value=Oppose_count*(-1)
    Appeal_value=Appeal_count*1
    Promise_value=Promise_count*2
    Reward_value=Reward_count*3
    total_words = (Punish_count+Threaten_count+Oppose_count+Neutral_count+Appeal_count+Promise_count+Reward_count)
    negative_value = (Punish_value+Threaten_value+Oppose_value)/3
    positive_value = (Appeal_value+Promise_value+Reward_value)/3
    index = (positive_value + negative_value) / total_words if total_words else 0.0

    # Output results
    print(f"Punish words count: {Punish_count}")
    print(f"Threaten words count: {Threaten_count}")
    print(f"Oppose words count: {Oppose_count}")
    print(f"Neutral words count: {Neutral_count}")
    print(f"Appeal words count: {Appeal_count}")
    print(f"Promise words count: {Promise_count}")
    print(f"Reward words count: {Reward_count}")
    print(f"Realisation of Political Values Index: {index:.2f}")

# Run the program
if __name__ == "__main__":
    main()
