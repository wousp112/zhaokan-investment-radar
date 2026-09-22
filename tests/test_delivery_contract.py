"""Regression gates for the original silent-video and timing failures."""
from copy import deepcopy

import pytest

from scripts.verify_demo import validate_contract


def fixture():
    probe={'format':{'duration':'146.2'},'streams':[
        {'codec_type':'video','codec_name':'h264','width':1920,'height':1080,
         'r_frame_rate':'30/1','pix_fmt':'yuv420p'},
        {'codec_type':'audio','codec_name':'aac','sample_rate':'48000'}]}
    chapters=[{'start':0,'end':60},{'start':60,'end':146.2}]
    captions=[{'start':.5,'end':3,'text':'第一句'},{'start':4,'end':7,'text':'第二句'}]
    return probe,chapters,captions


def test_valid_delivery_contract():
    assert validate_contract(*fixture())['audio_codec']=='aac'


def test_silent_movie_is_rejected_even_with_claimed_audio_flag():
    probe,chapters,captions=fixture();probe['streams'].pop();probe['has_audio']=True
    with pytest.raises(ValueError,match='narration stream'):
        validate_contract(probe,chapters,captions)


@pytest.mark.parametrize('duration',['59.9','180.1','nan','inf'])
def test_submission_duration_boundary(duration):
    probe,chapters,captions=fixture();probe['format']['duration']=duration
    with pytest.raises(ValueError,match='Duration'):
        validate_contract(probe,chapters,captions)


def test_wrong_picture_shape_is_rejected():
    probe,chapters,captions=fixture();probe['streams'][0]['height']=1160
    with pytest.raises(ValueError,match='1920'):
        validate_contract(probe,chapters,captions)


def test_chapter_gaps_are_rejected():
    probe,chapters,captions=fixture();chapters[1]['start']=65
    with pytest.raises(ValueError,match='Chapter'):
        validate_contract(probe,chapters,captions)


def test_overlapping_captions_are_rejected():
    probe,chapters,captions=fixture();captions[1]['start']=2.5
    with pytest.raises(ValueError,match='Caption'):
        validate_contract(probe,chapters,captions)
