# Plant Parent app architecture

> **Status**: ⚠️ **NOT YET IMPLEMENTED** - This is planned functionality that is still on the todo list.

## Overview

The Plant Parent app helps users track and manage their plant collection, including watering schedules, fertilizing needs, and care reminders.

## Core Features

### Settings and Memories

#### My Plants (`my_plants`)

A list-based memory that stores information about each plant in the user's collection. Each plant entry includes:

- **Basic Information**:
  - `name`: Plant name (required)
  - `species`: Plant species or common name
  - `location`: Where the plant is located (e.g., "Living room", "Kitchen window")
  - `acquired_date`: When the plant was acquired

- **Care Schedule**:
  - `watering_frequency_days`: Number of days between watering (required)
  - `fertilizing_frequency_days`: Number of days between fertilizing
  - `next_watering_date`: Next scheduled watering date (required, YYYY-MM-DD format)
  - `next_fertilizing_date`: Next scheduled fertilizing date (YYYY-MM-DD format)
  - `last_watered_date`: Last watering date (YYYY-MM-DD format)
  - `last_fertilized_date`: Last fertilizing date (YYYY-MM-DD format)

- **Additional Information**:
  - `notes`: Care notes, special instructions, or observations

### Focus Modes

#### Plant Care Guide (`plant_care_guide`)

A focus mode that helps users figure out how to properly care for specific plants. This mode guides users through a structured process to understand their plant's needs and get personalized care recommendations.

**Process:**

1. Identifies the plant (by name, species, or description)
2. Assesses current condition (leaves, growth, soil, etc.)
3. Evaluates environment (light, temperature, humidity, location)
4. Reviews current care routine (watering, fertilizing, repotting)
5. Identifies problems or concerns (yellowing leaves, pests, wilting, etc.)
6. Considers plant history (when acquired, recent changes, previous issues)
7. Provides personalized care recommendations
8. Suggests troubleshooting steps if needed
9. Helps update the plant care schedule in 'my_plants' settings and memories

**Use Cases:**

- Getting care instructions for a new plant
- Troubleshooting plant health issues
- Understanding why a plant isn't thriving
- Adjusting care schedule based on plant's needs
- Learning about specific plant requirements

**Status:** Draft/Planning - Not yet implemented

### Future Features

- **Skills**: Plant care skills that can provide:
  - Care recommendations based on plant type
  - Troubleshooting for common plant problems
  - Seasonal care adjustments
  - Plant identification assistance
  - Integration with plant care databases

## Data Model

Each plant is stored as a separate encrypted entry in the `user_app_settings_and_memories` collection, following the standard app settings and memories architecture. The system can automatically calculate next watering/fertilizing dates based on frequency and last care dates.

## Use Cases

1. **Track Plant Collection**: Store information about all plants in one place
2. **Schedule Management**: Automatically calculate and track next watering/fertilizing dates
3. **Care Reminders**: Get notified when plants need watering or fertilizing
4. **Care History**: Track when plants were last watered or fertilized
5. **Plant Care Guidance**: Use focus modes and skills to get personalized care recommendations
