# example.py

import random

def greet(name):
    """
    A simple function to greet a person.
    """
    return f"Hello, {name}! Welcome to Python."

class Die:
    """
    A class representing a die that can be rolled.
    """
    def __init__(self, sides=6):
        self.sides = sides
    
    def roll(self):
        return random.randint(1, self.sides)

# Main program
if __name__ == "__main__":
    # Greet the user
    user_name = input("What's your name? ")
    print(greet(user_name))
    
    # Create a die and roll it
    my_die = Die()
    roll_result = my_die.roll()
    print(f"You rolled a {roll_result}!")
    
    # Generate a list of random numbers
    numbers = [random.randint(1, 100) for _ in range(5)]
    print("Here are 5 random numbers between 1 and 100:")
    print(numbers)
    
    # Calculate and print the sum of the numbers
    total = sum(numbers)
    print(f"The sum of these numbers is: {total}")