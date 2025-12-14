import mido
from mido import MidiFile, MidiTrack, Message, MetaMessage
import csv
import os
import sys
import re

# --- Configuration ---
# Tempo 120 BPM = 0.5 seconds per beat
# 480 ticks per beat (standard resolution)
# Therefore: 960 ticks = 1 second
TICKS_PER_SECOND = 960 

def note_name_to_midi(note_name):
    """
    Converts a scientific pitch notation string (e.g., 'C4', 'F#5', 'Bb3')
    to a MIDI note number (0-127).
    Assumes C4 = MIDI 60.
    """
    note_name = note_name.strip().upper()
    
    # Regex to separate Letter+Accidental from Octave
    match = re.match(r"^([A-G][#B]?)(-?\d+)$", note_name)
    if not match:
        raise ValueError(f"Invalid note format: {note_name}")
        
    pitch_str, octave_str = match.groups()
    
    # Base offsets for C, D, E, F, G, A, B
    offsets = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
    
    base_pitch = offsets[pitch_str[0]]
    
    # Handle accidentals
    if len(pitch_str) > 1:
        if pitch_str[1] == '#':
            base_pitch += 1
        elif pitch_str[1] == 'B': # Handle flat (b)
            base_pitch -= 1
            
    octave = int(octave_str)
    
    # Formula: (Octave + 1) * 12 + Base
    midi_note = (octave + 1) * 12 + base_pitch
    
    # Clamp to MIDI range
    return max(0, min(127, midi_note))

def generate_24edo_sequencer(input_filename, output_filename):
    if not os.path.exists(input_filename):
        print(f"ERROR: Input file not found: {input_filename}")
        return

    # 1. Read and Parse Data
    # We need to store all events (Note On, Note Off, Pitch Bend) in a list
    # Structure: (absolute_time_in_ticks, priority, msg_type, note, value)
    all_events = []
    
    try:
        with open(input_filename, mode='r', newline='') as file:
            reader = csv.reader(file)
            next(reader, None) # Skip header
            for row in reader:
                if len(row) >= 5:
                    try:
                        # Columns: Note_Name, Pitch_Bend, Time, Velocity, Duration
                        raw_note = row[0].strip()
                        bend_val = int(row[1].strip())
                        velocity = int(round(float(row[2].strip()) * 127))
                        duration_sec = float(row[3].strip()) # Duration is now seconds
                        start_time_sec = float(row[4].strip())
                        
                        # Convert data
                        midi_note = note_name_to_midi(raw_note)
                        start_ticks = int(start_time_sec * TICKS_PER_SECOND)
                        duration_ticks = int(duration_sec * TICKS_PER_SECOND)
                        end_ticks = start_ticks + duration_ticks
                        
                        # Create Events
                        
                        # 1. Pitch Bend (Must happen just before Note On)
                        # Priority 0: Happens first at this timestamp
                        all_events.append({
                            'time': start_ticks, 
                            'priority': 0, 
                            'type': 'pitchwheel', 
                            'val': bend_val
                        })
                        
                        # 2. Note On
                        # Priority 1: Happens after bend
                        all_events.append({
                            'time': start_ticks, 
                            'priority': 1, 
                            'type': 'note_on', 
                            'note': midi_note, 
                            'vel': velocity
                        })
                        
                        # 3. Note Off
                        # Priority 2: Happens at end time
                        all_events.append({
                            'time': end_ticks, 
                            'priority': 0, # Priority doesn't matter much here, but good to be consistent
                            'type': 'note_off', 
                            'note': midi_note, 
                            'vel': 0
                        })

                    except ValueError as e:
                        print(f"Skipping invalid row {row}: {e}")
                        
    except Exception as e:
        print(f"File Error: {e}")
        return

    if not all_events:
        print("No valid events found.")
        return

    # 2. Sort Events
    # Sort primarily by Time, secondarily by Priority (so Bends happen before Notes)
    all_events.sort(key=lambda x: (x['time'], x['priority']))

    # 3. Write to MIDI
    mid = MidiFile(type=0)
    track = MidiTrack()
    mid.tracks.append(track)
    
    track.append(MetaMessage('set_tempo', tempo=500000, time=0))
    track.append(Message('program_change', program=0, time=0))
    
    last_tick_time = 0
    
    for event in all_events:
        # Calculate Delta Time (time since last event)
        delta_time = event['time'] - last_tick_time
        
        # Ensure delta is non-negative (sorting should ensure this, but safety first)
        if delta_time < 0: delta_time = 0
        
        if event['type'] == 'pitchwheel':
            track.append(Message('pitchwheel', pitch=event['val'], time=delta_time))
        elif event['type'] == 'note_on':
            track.append(Message('note_on', note=event['note'], velocity=event['vel'], time=delta_time))
        elif event['type'] == 'note_off':
            track.append(Message('note_off', note=event['note'], velocity=event['vel'], time=delta_time))
            
        last_tick_time = event['time']

    track.append(MetaMessage('end_of_track', time=0))
    mid.save(output_filename)
    print(f"Success! Saved to {output_filename}")

# --- Execution ---
if len(sys.argv) < 3:
    print("Usage: python script.py <input.csv> <output.mid>")
    # Create dummy file for user convenience if run without args
    dummy_csv = "sequencer_input.csv"
    if not os.path.exists(dummy_csv):
        with open(dummy_csv, 'w') as f:
            f.write("Note_Name,Pitch_Bend,Time,Velocity,Duration\n")
            f.write("C4,0,0.0,100,1.0\n")       # C4 at 0.0s for 1s
            f.write("C4,2048,1.0,100,1.0\n")    # C4 quarter-sharp at 1.0s
            f.write("E4,0,2.0,90,0.5\n")        # E4 at 2.0s
            f.write("G4,0,2.5,90,0.5\n")        # G4 at 2.5s
        print(f"Created demo input file: {dummy_csv}")
    sys.exit(1)

generate_24edo_sequencer(sys.argv[1], sys.argv[2])
