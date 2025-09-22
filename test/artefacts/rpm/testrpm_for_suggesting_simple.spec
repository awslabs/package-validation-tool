Name:           testrpm_for_suggesting_simple
Version:        0.1
Release:        1%{?dist}
Summary:        A test RPM package with one archive Source

License:        MIT
URL:            https://testrpmexample.com/testrpm_for_suggesting_simple

# Simple case: the package has one archive and one corresponding Source.
#
# Source0 is formatted to check transform_remove_url_fragment_from_spec_sources
# logic: the `#/archive.tar.gz` fragment must be removed as a result.
# Source0 is also formatted to check that remote-archive suggestions work even
# if the name and version of the archive are split (e.g. like GitHub does).
#
# Source1234 must be ignored by the tool, as it doesn't point to an archive.
Source0:        http://example.com/path/to/archive/version/0.1.tar.gz#/archive-0.1.tar.gz
Source1234:     some-license.pdf

BuildArch:      noarch

%description
This is a test RPM package with no archive Sources for testing purposes.

%prep
%autosetup

%build
# no-op

%install
mkdir -p %{buildroot}%{_bindir}
touch %{buildroot}%{_bindir}/testrpm_for_suggesting_simple

%files
%{_bindir}/testrpm_for_suggesting_simple

%changelog
* Wed Oct 01 2024 Your Name <your.email@testrpmexample.com> - 0.1-1
- Initial package
