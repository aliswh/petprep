from pathlib import Path

import nibabel as nb
import numpy as np
import pytest
from nipype.pipeline.engine.utils import generate_expanded_graph
from niworkflows.utils.testing import generate_bids_skeleton

from .... import config
from ...tests import mock_config
from ...tests.test_base import BASE_LAYOUT
from ..base import init_pet_wf


@pytest.fixture(scope='module', autouse=True)
def _quiet_logger():
    import logging

    logger = logging.getLogger('nipype.workflow')
    old_level = logger.getEffectiveLevel()
    logger.setLevel(logging.ERROR)
    yield
    logger.setLevel(old_level)


@pytest.fixture(scope='module')
def bids_root(tmp_path_factory):
    base = tmp_path_factory.mktemp('petbase')
    bids_dir = base / 'bids'
    generate_bids_skeleton(bids_dir, BASE_LAYOUT)
    return bids_dir


@pytest.mark.parametrize('task', ['rest'])
@pytest.mark.parametrize('level', ['minimal', 'resampling', 'full'])
@pytest.mark.parametrize('pet2anat_init', ['t1w', 't2w'])
@pytest.mark.parametrize('freesurfer', [False, True])
def test_pet_wf(
    bids_root: Path,
    tmp_path: Path,
    task: str,
    level: str,
    pet2anat_init: str,
    freesurfer: bool,
):
    """Test as many combinations of precomputed files and input
    configurations as possible."""
    output_dir = tmp_path / 'output'
    output_dir.mkdir()

    img = nb.Nifti1Image(np.zeros((10, 10, 10, 10)), np.eye(4))

    if task == 'rest':
        pet_series = [
            str(bids_root / 'sub-01' / 'pet' / 'sub-01_task-rest_run-1_pet.nii.gz'),
        ]


    # The workflow will attempt to read file headers
    for path in pet_series:
        img.to_filename(path)

    # Toggle running recon-all
    freesurfer = bool(freesurfer)

    with mock_config(bids_dir=bids_root):
        config.workflow.pet2anat_init = pet2anat_init
        config.workflow.level = level
        config.workflow.run_reconall = freesurfer
        wf = init_pet_wf(
            pet_series=pet_series,
            precomputed={},
        )

    flatgraph = wf._create_flat_graph()
    generate_expanded_graph(flatgraph)


def _prep_pet_series(bids_root: Path) -> list[str]:
    """Generate dummy PET data for testing."""
    pet_series = [
        str(bids_root / 'sub-01' / 'pet' / 'sub-01_task-rest_run-1_pet.nii.gz')
    ]
    img = nb.Nifti1Image(np.zeros((10, 10, 10, 10)), np.eye(4))
    for path in pet_series:
        img.to_filename(path)
    return pet_series


def test_pet_wf_with_pvc(bids_root: Path):
    """PET workflow includes the PVC workflow when configured."""
    pet_series = _prep_pet_series(bids_root)

    with mock_config(bids_dir=bids_root):
        config.workflow.pvc_tool = 'PETPVC'
        config.workflow.pvc_method = 'GTM'
        config.workflow.pvc_psf = (1.0, 1.0, 1.0)

        wf = init_pet_wf(pet_series=pet_series, precomputed={})

    assert 'pet_pvc_wf' in [n.split('.')[-1] for n in wf.list_node_names()]


def test_pet_wf_without_pvc(bids_root: Path):
    """PET workflow does not include the PVC workflow by default."""
    pet_series = _prep_pet_series(bids_root)

    with mock_config(bids_dir=bids_root):
        wf = init_pet_wf(pet_series=pet_series, precomputed={})

    assert 'pet_pvc_wf' not in [n.split('.')[-1] for n in wf.list_node_names()]


def test_pvc_entity_added(bids_root: Path):
    """Outputs include the ``pvc`` entity when PVC is run."""
    pet_series = _prep_pet_series(bids_root)

    with mock_config(bids_dir=bids_root):
        config.workflow.pvc_tool = 'PETPVC'
        config.workflow.pvc_method = 'GTM'
        config.workflow.pvc_psf = (1.0, 1.0, 1.0)

        wf = init_pet_wf(pet_series=pet_series, precomputed={})

    pvc_method = config.workflow.pvc_method
    assert wf.get_node('ds_pet_t1_wf.ds_pet').inputs.pvc == pvc_method
    assert wf.get_node('ds_pet_std_wf.ds_pet').inputs.pvc == pvc_method
    assert wf.get_node('pet_surf_wf.ds_pet_surfs').inputs.pvc == pvc_method
    assert wf.get_node('ds_pet_cifti').inputs.pvc == pvc_method


def test_pvc_used_in_std_space(bids_root: Path):
    """Standard-space outputs should originate from PVC data when enabled."""
    pet_series = _prep_pet_series(bids_root)

    with mock_config(bids_dir=bids_root):
        config.workflow.pvc_tool = 'PETPVC'
        config.workflow.pvc_method = 'GTM'
        config.workflow.pvc_psf = (1.0, 1.0, 1.0)

        wf = init_pet_wf(pet_series=pet_series, precomputed={})

    # Connection from PVC workflow to standard-space workflow
    edge = wf._graph.get_edge_data(wf.get_node('pet_pvc_wf'), wf.get_node('pet_std_wf'))
    assert ('outputnode.pet_pvc_file', 'inputnode.pet_file') in edge['connect']

    # Ensure uncorrected PET is not used as the source image
    edge_native = wf._graph.get_edge_data(wf.get_node('pet_native_wf'), wf.get_node('pet_std_wf'))
    assert ('outputnode.pet_minimal', 'inputnode.pet_file') not in edge_native['connect']
