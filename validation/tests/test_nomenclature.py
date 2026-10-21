from types import SimpleNamespace
import pytest
from openrad.validation.nomenclature import catalogue, check_structure_name, build_roi_index, tg263_dvh_metrics


def roi(number, name):
    return SimpleNamespace(ROINumber=number, ROIName=name)


def test_pinned_vocabulary():
    data = catalogue()
    assert len(data['structures']) == 717
    assert len(data['source_sha256']) == 64
    for entry in data['structures']:
        assert check_structure_name(entry['primary'])['status'] == 'official_primary'


@pytest.mark.parametrize('name', ['SpinalCord', 'Brainstem', 'Lung_L', 'Lung_R'])
def test_primary_names(name):
    assert check_structure_name(name)['canonical_name'] == name


@pytest.mark.parametrize('name', ['PTV_High', 'PTV_Mid01', 'PTV_5040', 'PTV_50.4Gy', 'PTV_50p4Gy', 'PTV-03', 'GTVp2', 'PTV!_Low'])
def test_supported_targets(name):
    assert check_structure_name(name)['status'] == 'target_pattern_checked'


@pytest.mark.parametrize('name', ['Cord', 'PTV 69.96 Gy', 'PTV_50.4', 'ImaginaryOrgan', 'PTVn_invalid', 'SpinalCordExtraLong'])
def test_review_required_does_not_mean_invalid(name):
    assert check_structure_name(name)['status'] == 'review_required'


def test_case_variant_is_reported():
    report = check_structure_name('lung_l')
    assert report['canonical_name'] == 'Lung_L'
    assert report['issues']


def test_laterality_and_qualifiers_are_never_stripped():
    index, _ = build_roi_index([roi(1, 'Lung_L'), roi(2, 'Lung_R'), roi(3, 'Lung~_L'), roi(4, 'Lung_L^Ex')])
    assert index['lung_l']['roi_number'] == 1
    assert index['lung_r']['roi_number'] == 2
    assert 'lung' not in index
    assert index['lung_l^ex']['canonical_name'] is None
    assert index['lung~_l']['roi_number'] == 3


@pytest.mark.parametrize('rois,mapping', [([roi(1,'Lung_L'),roi(2,'lung_l')],None), ([roi(1,'Lung_L'),roi(1,'Lung_R')],None), ([roi(1,'Cord'),roi(2,'SpinalCord')],{'Cord':'SpinalCord'})])
def test_collisions_block(rois, mapping):
    with pytest.raises(ValueError, match='ambiguous'):
        build_roi_index(rois, mapping)


def test_reviewed_legacy_mapping_is_explicit_and_preserved():
    index, _ = build_roi_index([roi(1, 'Cord')], {'Cord': 'SpinalCord'})
    assert index['spinalcord']['original_name'] == 'Cord'
    assert index['cord']['canonical_name'] == 'SpinalCord'
    assert index['cord']['status'] == 'reviewed_mapping'


def test_missing_mapping_source_rejected():
    with pytest.raises(ValueError):
        build_roi_index([roi(1, 'Lung_L')], {'Absent': 'Lung_R'})


def test_dvh_labels_keep_dose_and_volume_units_distinct():
    metrics = tg263_dvh_metrics(60, 65, 70, 30, 12)
    assert metrics == {'D95%[Gy]': 60, 'D50%[Gy]': 65, 'D2%[Gy]': 70, 'V50Gy[%]': 30, 'V50Gy[cc]': 12}
    assert 'V50%' not in metrics


@pytest.mark.parametrize('name', ['OpticNrv_PRV03_L', 'SpinalCord_PRV05', 'Brainstem_PRV', 'Lung~_L'])
def test_derived_organ_patterns(name):
    assert check_structure_name(name)['canonical_name'] == name
    assert check_structure_name(name)['status'] in {'derived_pattern_checked', 'official_primary'}


def test_dvh_integration_preserves_source_and_blocks_unreviewed_alias(monkeypatch):
    import numpy as np
    from openrad.tools.dicom_tool import analyze_dvh
    dose = SimpleNamespace(SOPClassUID='1.2.840.10008.5.1.4.1.1.481.2', SOPInstanceUID='1.2.3.4', Rows=5, Columns=5, Modality='RTDOSE', DoseUnits='GY', DoseType='PHYSICAL',
        DoseGridScaling=1., PixelSpacing=[1., 1.], ImagePositionPatient=[0.,0.,0.],
        ImageOrientationPatient=[1.,0.,0.,0.,1.,0.], GridFrameOffsetVector=[0.,1.,2.],
        NumberOfFrames=3, FrameOfReferenceUID='1.2.3', PatientID='synthetic',
        pixel_array=np.full((3, 5, 5), 60.))
    source_roi = roi(1, 'Cord')
    source_roi.ReferencedFrameOfReferenceUID = '1.2.3'
    struct = SimpleNamespace(Modality='RTSTRUCT', SOPClassUID='1.2.840.10008.5.1.4.1.1.481.3', SOPInstanceUID='1.2.3.5', PatientID='synthetic', StructureSetROISequence=[source_roi],
        ROIContourSequence=[SimpleNamespace(ReferencedROINumber=1,
            ContourSequence=[SimpleNamespace(ContourGeometricType="CLOSED_PLANAR", NumberOfContourPoints=4, ContourData=[0,0,z,4,0,z,4,4,z,0,4,z]) for z in (0,1)])])
    monkeypatch.setattr('openrad.tools.dicom_tool.os.path.exists', lambda _: True)
    monkeypatch.setattr('openrad.tools.dicom_tool.pydicom.dcmread', lambda path: struct if path=='struct' else dose)
    blocked = analyze_dvh('struct', 'dose', ['Cord'])
    assert not blocked['structures']['Cord']['found']
    accepted = analyze_dvh('struct', 'dose', ['SpinalCord'], {'Cord':'SpinalCord'})
    result = accepted['structures']['SpinalCord']
    assert result['found']
    assert result['structure_name'] == 'Cord'
    assert result['canonical_structure_name'] == 'SpinalCord'
    assert result['tg263_metrics']['D95%[Gy]'] == 60
    assert result['tg263_metrics']['V50Gy[%]'] == 100
    assert source_roi.ROIName == 'Cord'
