#!/usr/bin/env python3

# Many thanks to https://github.com/danielgtaylor/qtrotate for this script.
# Figuring out how to rotate videos was a huge pain. This script is a lifesaver.

"""
    QT Rotate
    =========
    Detect Rotated Quicktime/MP4 files. This script will spit out a rotation
    angle if one can be found. It can also write an new rotation angle.
    
    NOTE that translation info will be LOST if a new rotation angle is written.

    Usage:
    #read rotation angle
    bash-3.2$ ./qtrotate.py thomas.mp4 
    0

    #set new rotation angle
    bash-3.2$ ./qtrotate.py thomas.mp4 90

    #read new rotation angle
    bash-3.2$ ./qtrotate.py thomas.mp4 
    90

"""

import math
import os
import struct
import sys

def read_atom(datastream):
    """
        Read an atom and return a tuple of (size, type) where size is the size
        in bytes (including the 8 bytes already read) and type is a "fourcc"
        like "ftyp" or "moov".
    """
    return struct.unpack(">L4s", datastream.read(8))

def get_index(datastream):
    """
        Return an index of top level atoms, their absolute byte-position in the
        file and their size in a list:
        
        index = [
            ("ftyp", 0, 24),
            ("moov", 25, 2658),
            ("free", 2683, 8),
            ...
        ]
        
        The tuple elements will be in the order that they appear in the file.
    """
    index = []
    
    # Read atoms until we catch an error
    while(datastream):
        try:
            atom_size, atom_type = read_atom(datastream)
        except:
            break
        index.append((atom_type.decode(), datastream.tell() - 8, atom_size))
        
        if atom_size < 8:
            break
        else:
            datastream.seek(atom_size - 8, os.SEEK_CUR)
    
    # Make sure the atoms we need exist
    top_level_atoms = set([item[0] for item in index])
    for key in ["ftyp", "moov", "mdat"]:
        if key not in top_level_atoms:
            print("%s atom not found, is this a valid MOV/MP4 file?" % key)
            raise SystemExit(1)
    
    return index

def find_atoms(size, datastream):
    """
        This function is a generator that will yield either "mvhd" or "tkhd"
        when either atom is found. datastream can be assumed to be 8 bytes
        into the atom when the value is yielded.
        
        It is assumed that datastream will be at the end of the atom after
        the value has been yielded and processed.
        
        size is the number of bytes to the end of the atom in the datastream.
    """
    stop = datastream.tell() + size
    
    while datastream.tell() < stop:
        try:
            atom_size, atom_type = read_atom(datastream)
        except:
            print("Error reading next atom!")
            raise SystemExit(1)
        
        if atom_type in [b"trak"]:
            # Known ancestor atom of stco or co64, search within it!
            for atype in find_atoms(atom_size - 8, datastream):
                yield atype
        elif atom_type in [b"mvhd", b"tkhd"]:
            yield atom_type.decode()
        else:
            # Ignore this atom, seek to the end of it.
            datastream.seek(atom_size - 8, os.SEEK_CUR)

def get_set_rotation(infilename, set_degrees=None):
    """
        Get and return the degrees of rotation in a file, or -1 if it cannot
        be determined.
    
        See ISO 14496-12:2005 and 
        http://developer.apple.com/documentation/QuickTime/QTFF/QTFFChap2/chapter_3_section_2.html#//apple_ref/doc/uid/TP40000939-CH204-56313
    """
    datastream = open(infilename, "r+b")
    
    # Get the top level atom index
    index = get_index(datastream)
    
    for atom, pos, size in index:
        if atom == "moov":
            moov_size = size
            datastream.seek(pos + 8)
            break
    else:
        print("Couldn't find moov!")
        raise SystemExit(1)
    
    degrees = set()
    
    for atom_type in find_atoms(moov_size - 8, datastream):
        #print atom_type + " found!"
        vf = datastream.read(4)
        version = struct.unpack(">Bxxx", vf)[0]
        flags = struct.unpack(">L", vf)[0] & 0x00ffffff
        if version == 1:
            if atom_type == "mvhd":
                datastream.read(28)
            elif atom_type == "tkhd":
                datastream.read(32)
        elif version == 0:
            if atom_type == "mvhd":
                datastream.read(16)
            elif atom_type == "tkhd":
                datastream.read(20)
        else:
            print("Unknown %s version: %d!" % (atom_type, version))
            raise SystemExit(1)
        
        datastream.read(16)
        
        matrix = list(struct.unpack(">9l", datastream.read(36)))        

        if ('tkhd' == atom_type) and (set_degrees != None):
            radians = math.radians(set_degrees)
            cos_deg = int((1<<16)*math.cos(radians))
            sin_deg = int((1<<16)*math.sin(radians))
            value = struct.pack(">9l", cos_deg, sin_deg, 0, -sin_deg, cos_deg, 0, 0, 0, (1<<30))
            datastream.seek(-36, 1)
            datastream.write(value)

        else:        
            for x in range(9):
                if (x + 1) % 3:
                    #print x, matrix[x]
                    matrix[x] = float(matrix[x]) / (1 << 16)
                else:
                    #print x, matrix[x]
                    matrix[x] = float(matrix[x]) / (1 << 30)
        
            #print matrix
            
    
            #for row in [matrix[:3], matrix[3:6], matrix[6:]]:
            #    print "\t".join([str(round(item, 1)) for item in row])
            #print ""
            
            if atom_type in ["mvhd", "tkhd"]:
                deg = -math.degrees(math.asin(matrix[3])) % 360
                if not deg:
                    deg = math.degrees(math.acos(matrix[0]))
                if deg:
                    degrees.add(deg)
        
        if atom_type == "mvhd":
            datastream.read(28)
        elif atom_type == "tkhd":
            datastream.read(8)

    if len(degrees) == 0:
        return 0
    elif len(degrees) == 1:
        return degrees.pop()
    else:
        return -1

if __name__ == "__main__":
    try:    
        if 3==len(sys.argv):
            set_degrees = int(sys.argv[2])
            # print "Forcing transformation matrix to %d degrees..." % set_degrees
            deg = get_set_rotation(sys.argv[1], set_degrees)
        else:
            deg = get_set_rotation(sys.argv[1])

            if deg == -1:
                deg = 0
        
            print(int(deg))
            
    except Exception as e:
        print(e)
        raise SystemExit(1)
