# Dataset sources, attribution and access notes

Reviewed 23 October 2026. Credit the data creators and the distribution used, separately from OpenRad's software. Source availability, citation and permission to redistribute are distinct questions. None of the sources below endorses OpenRad or establishes clinical validation.

## HNSCC: Zenodo distribution and original TCIA collection

The project owner identifies [Zenodo record 5276878](https://zenodo.org/records/5276878) as the source of the local HNSCC files. Cite both that distribution and the original collection:

- Finnegan, R. (2021). **HNSCC**, version v1 [Dataset]. Zenodo. [doi:10.5281/zenodo.5276878](https://doi.org/10.5281/zenodo.5276878).
- Grossberg, A., et al., and the M.D. Anderson Cancer Center Head and Neck Quantitative Imaging Working Group (2020). **HNSCC** [Dataset]. The Cancer Imaging Archive. [doi:10.7937/k9/tcia.2020.a8sh-7363](https://doi.org/10.7937/k9/tcia.2020.a8sh-7363).

The Zenodo record also requests these references when the data is used in research:

- Grossberg, A., et al. (2018). **Imaging and clinical data archive for head and neck squamous cell carcinoma patients treated with radiotherapy.** *Scientific Data*, 5, 180173. [doi:10.1038/sdata.2018.173](https://doi.org/10.1038/sdata.2018.173).
- Elhalawani, H., et al. (2017). **Matched computed tomography segmentation and demographic data for oropharyngeal cancer radiomics challenges.** *Scientific Data*, 4, 170077. [doi:10.1038/sdata.2017.77](https://doi.org/10.1038/sdata.2017.77).
- Clark, K., et al. (2013). **The Cancer Imaging Archive (TCIA): Maintaining and Operating a Public Information Repository.** *Journal of Digital Imaging*, 26, 1045–1057. [doi:10.1007/s10278-013-9622-7](https://doi.org/10.1007/s10278-013-9622-7).

**Terms:** the 2021 Zenodo description names [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) and incorporates the TCIA usage policy. CC BY requires appropriate attribution and a license link; retain supplied notices and identify derivatives as applicable. It does not resolve all privacy or other rights. The [TCIA policy page](https://wiki.cancerimagingarchive.net/display/Public/Data+Usage+Policies+and+Restrictions) also describes later access changes for head/neck collections and requires collection-specific checks. Its current collection landing page could not be retrieved during this review. This document records the historical notice; it does not certify present redistribution rights. Use the [current TCIA policy entry point](https://www.cancerimagingarchive.net/data-usage-policies-and-restrictions/) and collection terms before additional reuse or redistribution.

**OpenRad use:** local read-only intake and selected engineering checks, not training a newly validated predictive model. Raw HNSCC files are not needed for the synthetic judge's tour and are not added to this repository by these documentation changes. Keep original files unchanged and derivatives separate. Public documentation must not include private local paths, source patient identifiers or identifying screenshots.

## SlicerRtData: sample DICOM-RT test collections

Suggested attribution:

> SlicerRt contributors. **SlicerRtData: Sample DICOM-RT datasets for demonstration and testing purposes.** GitHub repository, revision `704936e8889c77174a0dd97cfb8703b47952e62c`. Accessed 23 October 2026. [Pinned source tree](https://github.com/SlicerRt/SlicerRtData/tree/704936e8889c77174a0dd97cfb8703b47952e62c).

OpenRad's [selected benchmark manifest](../validation/benchmarks/slicerrt/manifest.json) records source paths, sizes and Git blob hashes. The [benchmark methodology](../validation/benchmarks/slicerrt/README.md) explains supported and unsupported cases, comparison settings and discrepancies. Downloaded caches stay under ignored raw-data storage; they are not the packaged synthetic demo.

No dataset-specific license was identified in the pinned repository-root inventory. Do not apply the SlicerRT **software** license automatically to every sample dataset. Check notices and original-source terms for the selected subcollection before redistributing it. A repository citation credits the collection but does not settle those permissions. Describe these as compatibility/numerical test inputs, not universally qualified ground truth; the SlicerRT application itself was not executed in OpenRad's recorded comparison.

## OpenRad synthetic demonstration files

The files under [`data/demo/`](../data/demo/README.md) are artificial examples produced by [`src/demo.py`](../src/demo.py), with deliberate clean and defective variants. Credit them as **OpenRad-Agent synthetic teaching fixtures**. They are not copied patient cases from either source above and do not represent a commissioned treatment plan. Their byte inventory is in [`SHA256SUMS.json`](../data/demo/SHA256SUMS.json).

## Where credits belong

Keep full references here, a short acknowledgement in the root README, and source links in benchmark reports. Include relevant data credits in the write-up and presentation references when discussing those datasets or their results. A synthetic-only figure should say it is artificial OpenRad data; it should not be captioned as an HNSCC patient or SlicerRT phantom. Preserve original source, revision, applicable terms and changes when creating a derived dataset. Cite scientific software separately where it contributes to an analysis.
