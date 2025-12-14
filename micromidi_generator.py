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

def write_events_to_track(track, event_list, channel):
    """
    Helper function to write a sorted list of events to a specific MIDI track.
    Calculates delta times based on the specific event list.
    """
    last_tick_time = 0
    
    # Ensure events are sorted by time, then priority
    event_list.sort(key=lambda x: (x['time'], x['priority']))

    for event in event_list:
        # Calculate Delta Time relative to THIS track's last event
        delta_time = event['time'] - last_tick_time
        if delta_time < 0: delta_time = 0
        
        if event['type'] == 'pitchwheel':
            track.append(Message('pitchwheel', channel=channel, pitch=event['val'], time=delta_time))
        elif event['type'] == 'note_on':
            track.append(Message('note_on', channel=channel, note=event['note'], velocity=event['vel'], time=delta_time))
        elif event['type'] == 'note_off':
            track.append(Message('note_off', channel=channel, note=event['note'], velocity=event['vel'], time=delta_time))
            
        last_tick_time = event['time']

def generate_24edo_sequencer(input_filename, output_filename):
    if not os.path.exists(input_filename):
        print(f"ERROR: Input file not found: {input_filename}")
        return

    # 1. Parsing
    # We will split events into two lists immediately
    clean_events = [] # For Channel 0 (No bend)
    bent_events = []  # For Channel 1 (With bend)
    
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
                        duration_sec = float(row[3].strip())
                        start_time_sec = float(row[4].strip())
                        
                        midi_note = note_name_to_midi(raw_note)
                        start_ticks = int(start_time_sec * TICKS_PER_SECOND)
                        duration_ticks = int(duration_sec * TICKS_PER_SECOND)
                        end_ticks = start_ticks + duration_ticks
                        
                        # Determine which list and channel logic to use
                        # If bend is NOT 0, it goes to the "Bent" track
                        # If bend IS 0, it goes to the "Clean" track
                        target_list = bent_events if bend_val != 0 else clean_events
                        
                        # --- Create Events ---
                        
                        # Only add pitch bend event if it is the bent track
                        if bend_val != 0:
                            target_list.append({
                                'time': start_ticks, 
                                'priority': 0, 
                                'type': 'pitchwheel', 
                                'val': bend_val
                            })
                        
                        # Note On
                        target_list.append({
                            'time': start_ticks, 
                            'priority': 1, 
                            'type': 'note_on', 
                            'note': midi_note, 
                            'vel': velocity
                        })
                        
                        # Note Off
                        target_list.append({
                            'time': end_ticks, 
                            'priority': 0,
                            'type': 'note_off', 
                            'note': midi_note, 
                            'vel': 0
                        })

                    except ValueError as e:
                        print(f"Skipping invalid row {row}: {e}")
                        
    except Exception as e:
        print(f"File Error: {e}")
        return

    if not clean_events and not bent_events:
        print("No valid events found.")
        return

    # 2. Write to MIDI
    # Type 1 = Multi-track synchronous
    mid = MidiFile(type=1)
    
    # --- Track 1: Meta Data & Clean Notes (Channel 0) ---
    track_clean = MidiTrack()
    track_clean.name = "Standard Notes"
    mid.tracks.append(track_clean)
    
    # Add Tempo/Meta to the first track
    track_clean.append(MetaMessage('set_tempo', tempo=500000, time=0))
    track_clean.append(Message('program_change', channel=0, program=0, time=0))
    
    # Write clean events to Channel 0
    write_events_to_track(track_clean, clean_events, channel=0)
    track_clean.append(MetaMessage('end_of_track', time=0))

    # --- Track 2: Bent Notes (Channel 1) ---
    if bent_events:
        track_bent = MidiTrack()
        track_bent.name = "Microtonal Notes"
        mid.tracks.append(track_bent)
        
        # Initialize Channel 1
        track_bent.append(Message('program_change', channel=1, program=0, time=0))
        
        # Write bent events to Channel 1
        write_events_to_track(track_bent, bent_events, channel=1)
        track_bent.append(MetaMessage('end_of_track', time=0))

    mid.save(output_filename)
    print(f"Success! Saved to {output_filename}")
    print(f"Stats: {len(clean_events)//2} standard notes, {len(bent_events)//3} bent notes.")

# --- Execution ---
if len(sys.argv) < 3:
    print("Usage: python script.py <input.csv> <output.mid>")
    # Create dummy file for user convenience if run without args
    dummy_csv = "sequencer_input.csv"
    if not os.path.exists(dummy_csv):
        with open(dummy_csv, 'w') as f:
            f.write("Note_Name,Pitch_Bend,Time,Velocity,Duration\n")
            f.write("C4,0,0.0,100,1.0\n")       # Clean Track
            f.write("C4,2048,0.5,100,1.0\n")    # Bent Track (Overlap to test interference)
            f.write("E4,0,2.0,90,0.5\n")        # Clean Track
            f.write("G4,-2048,2.5,90,0.5\n")    # Bent Track
        print(f"Created demo input file: {dummy_csv}")
    sys.exit(1)

generate_24edo_sequencer(sys.argv[1], sys.argv[2])