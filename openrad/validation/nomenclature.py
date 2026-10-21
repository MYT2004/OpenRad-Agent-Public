"""TG-263 nomenclature checks; names cannot establish anatomical correctness.

Pinned official non-target vocabulary plus a deliberately bounded target grammar.
Unrecognized forms need review, rather than being declared noncompliant or renamed.
"""
import json
import re
from functools import lru_cache
from importlib.resources import files
from typing import Dict, Optional


@lru_cache(maxsize=1)
def catalogue():
    return json.loads(files('openrad').joinpath('data/tg263_20170815.json').read_text())


# Section 8: supported subset includes type/classifier/enumerator, relative or
# physical dose, fractionation and cropping. Imaging/anatomic/custom target
# qualifiers and compressed forms intentionally require human review.
_TARGET = re.compile(
    r'(?:IGTV|ICTV|GTV|CTV|ITV|PTV)!?(?:n|p|sb|par|v|vas)?[0-9]*'
    r'(?:_(?:High|Low|Mid(?:[0-9]{2})?|[0-9]+(?:[.p][0-9]+)?Gy(?:x[0-9]+)?|[0-9]+(?:x[0-9]+)?))?'
    r'(?:-[0-9]{2})?'
)


@lru_cache(maxsize=1)
def _primary_names():
    return {r['primary'].casefold(): r['primary'] for r in catalogue()['structures']}


def _derived_primary(name):
    """Recognize section 7.2 PRV and partial-volume forms of known organs."""
    match = re.fullmatch(r'(.+?)(~)?(?:_PRV([0-9]{1,2})?)?(_(?:L|R|A|P|I|S|RUL|RLL|RML|LUL|LLL|NAdj|Dist|Prox))?', name)
    if not match or ('~' not in name and '_PRV' not in name):
        return None
    root, partial, margin, spatial = match.groups()
    base = root + (spatial or '')
    if '_PRV' in root or '~' in root or base.casefold() not in _primary_names():
        return None
    canonical_base = _primary_names()[base.casefold()]
    canonical_root = canonical_base[:-len(spatial)] if spatial else canonical_base
    return canonical_root + ('~' if partial else '') + ('_PRV' + (margin or '') if '_PRV' in name else '') + (spatial or '')


def check_structure_name(name: str) -> dict:
    """Return a scoped verdict without altering the supplied name."""
    if not isinstance(name, str) or not name:
        raise ValueError('ROI names must be nonempty strings.')
    result = {'original_name': name, 'canonical_name': None,
              'status': 'review_required', 'issues': []}
    if len(name) > 16:
        result['issues'].append('Exceeds the TG-263 16-character naming recommendation.')
    if any(c.isspace() for c in name):
        result['issues'].append('Whitespace is not used in TG-263 structure names.')
    if result['issues']:
        return result
    primary = _primary_names()
    reverse = {r['reverse'].casefold(): r['primary'] for r in catalogue()['structures']}
    if name.casefold() in primary:
        canonical = primary[name.casefold()]
        result.update(canonical_name=canonical, status='official_primary')
        if name != canonical:
            result['issues'].append('Capitalization differs from the official primary spelling.')
    elif _derived_primary(name):
        result.update(canonical_name=_derived_primary(name), status='derived_pattern_checked')
        result['issues'].append('PRV margin/partial-volume naming only; geometry and completeness require clinical review.')
    elif name.casefold() in reverse:
        result['issues'].append('Official reverse-order name; review before mapping to the preferred primary name.')
        result['suggested_primary_name'] = reverse[name.casefold()]
    elif _TARGET.fullmatch(name):
        result.update(canonical_name=name, status='target_pattern_checked')
        result['issues'].append('Target syntax subset only; verify dose, fractionation and segmentation against clinical records.')
    else:
        result['issues'].append('Not in the pinned primary vocabulary or supported target subset; review required. This is not proof of TG-263 noncompliance.')
    return result


def build_roi_index(rois, reviewed_name_map: Optional[Dict[str, str]] = None):
    """Index unique source names and explicitly reviewed canonical mappings.

    Mapping keys are exact source names; values must be official primary names or
    supported target names. No fuzzy matching, stripping or laterality inference.
    """
    mappings = reviewed_name_map or {}
    entries, numbers, source_keys = [], set(), set()
    for roi in rois:
        number, name = int(roi.ROINumber), str(roi.ROIName)
        key = name.casefold()
        if number in numbers or key in source_keys:
            raise ValueError('Duplicate ROI number or case-insensitive ROI name; selection is ambiguous.')
        numbers.add(number)
        source_keys.add(key)
        verdict = check_structure_name(name)
        if name in mappings:
            mapped = check_structure_name(mappings[name])
            if mapped['canonical_name'] is None:
                raise ValueError('Reviewed mapping must resolve to a supported TG-263 primary or target name.')
            verdict.update(canonical_name=mapped['canonical_name'], status='reviewed_mapping')
            verdict['issues'].append('Caller-supplied reviewed mapping; anatomical equivalence is not inferred by software.')
        entries.append({'roi_number': number, **verdict})
    if set(mappings) - {e['original_name'] for e in entries}:
        raise ValueError('Reviewed mapping references an absent source ROI.')
    index = {}
    for entry in entries:
        for key in {entry['original_name'].casefold(), (entry['canonical_name'] or entry['original_name']).casefold()}:
            if key in index and index[key]['roi_number'] != entry['roi_number']:
                raise ValueError('Canonical/source ROI names collide; selection is ambiguous.')
            index[key] = entry
    return index, entries


def tg263_dvh_metrics(d95, d50, d2, v50_percent, v50_cc):
    """Section 9.2: explicit input units and bracketed output units."""
    return {'D95%[Gy]': float(d95), 'D50%[Gy]': float(d50),
            'D2%[Gy]': float(d2), 'V50Gy[%]': float(v50_percent),
            'V50Gy[cc]': float(v50_cc)}
