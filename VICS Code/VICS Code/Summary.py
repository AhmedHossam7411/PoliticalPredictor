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
    total_count = sum(word_counts[word.lower()] for word in words if word.lower() in word_counts)
    return total_count

# Main function
def main():
    base_path = os.path.dirname(os.path.abspath(__file__))

    # File paths for "Others" attributions
    others_words_folder = os.path.join(base_path, 'QP', 'Q1P_txt')
    positive_others_file = os.path.join(others_words_folder, 'positive_words.txt')
    negative_others_file = os.path.join(others_words_folder, 'negative_words.txt')

    # File paths for "Self" attributions
    self_words_folder = os.path.join(base_path, 'QI', 'Q1I_txt', 'Lists Q1I')
    positive_self_file = os.path.join(self_words_folder, 'positive_self_attributions.txt')
    negative_self_file = os.path.join(self_words_folder, 'negative_self_attributions.txt')

    input_text_file = os.path.join(base_path, 'input_text.txt')

    # Load words
    positive_others = load_words(positive_others_file)
    negative_others = load_words(negative_others_file)
    positive_self = load_words(positive_self_file)
    negative_self = load_words(negative_self_file)

    # Load input text
    try:
        with open(input_text_file, 'r', encoding='utf-8') as file:
            text = file.read()
    except FileNotFoundError:
        print(f"Error: Input text file not found - {input_text_file}")
        return

    # Count words for "Others"
    positive_others_count = count_words_in_text(text, positive_others)
    negative_others_count = count_words_in_text(text, negative_others)
    total_others = positive_others_count + negative_others_count
    POP=positive_others_count/total_others
    NOP=negative_others_count/total_others

    # Count words for "Self"
    positive_self_count = count_words_in_text(text, positive_self)
    negative_self_count = count_words_in_text(text, negative_self)
    total_self = positive_self_count + negative_self_count
    PSP=positive_self_count/total_self
    NSP=negative_self_count/total_self

    index=((PSP-NSP)-(POP-NOP))/2


    # Output results
    print(f"Positive Others Attributions words count: {positive_others_count}")
    print(f"Negative Others Attributions words count: {negative_others_count}")
    print(f"Positive Self Attributions words count: {positive_self_count}")
    print(f"Negative Self Attributions words count: {negative_self_count}")
    print(f"Summary Index: {index:.2f}")

# Run the program
if __name__ == "__main__":
    main()
