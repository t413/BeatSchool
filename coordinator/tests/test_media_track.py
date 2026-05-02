import pytest, tempfile, os
from core.media_track import MediaTrack

def test_media_track_initialization():
    """Test MediaTrack initialization"""
    path = "/fake/path/song.mp3"
    track = MediaTrack(path)
    assert track.path == path
    assert track.analyzed == False
    assert track.duration == 0.0
    assert track.beats == []
    assert track.onsets == []
    assert track.name == "song"

def test_media_track_to_json():
    """Test MediaTrack to_json method"""
    track = MediaTrack("/fake/path/test.mp3")
    track.analyzed = True
    track.duration = 120.5
    track.beats = [1.0, 2.0, 3.0]
    track.onsets = [0.5, 1.5, 2.5]

    json_data = track.to_json()
    assert json_data['name'] == 'test'
    assert json_data['analyzed'] == True
    assert json_data['duration'] == 120.5
    assert json_data['beats'] == [1.0, 2.0, 3.0]
    assert json_data['onsets'] == [0.5, 1.5, 2.5]

def test_media_track_cache_path():
    """Test cache path generation"""
    track = MediaTrack("/some/dir/song.mp3")
    cache_path = track.cache_path
    assert str(cache_path) == "/some/dir/song.pkl"

def test_media_track_load_from_disk_no_cache():
    """Test loading when no cache exists"""
    track = MediaTrack("/nonexistent.mp3")
    assert track.load_from_disk() == False

def test_media_track_save_to_disk():
    """Test saving analysis to disk"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.mp3")
        track = MediaTrack(path)
        track.analyzed = True
        track.duration = 100.0
        track.beats = [10.0, 20.0]
        track.onsets = [5.0, 15.0]

        track.save_to_disk()

        # Verify cache file exists
        cache_file = track.cache_path
        assert os.path.exists(cache_file)

        # Load and verify
        new_track = MediaTrack(path)
        assert new_track.load_from_disk() == True
        assert new_track.analyzed == True
        assert new_track.duration == 100.0
        assert new_track.beats == [10.0, 20.0]
        assert new_track.onsets == [5.0, 15.0]
