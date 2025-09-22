Name:           testrpm_for_suggesting
Version:        0.1
Release:        1%{?dist}
Summary:        A test RPM package with broken/tricky Sources

License:        MIT
URL:            https://testrpmexample.com/testrpm_for_suggesting

# In some cases, maintainers of the package choose to fold multiple source-code
# archives in a single huge archive. To suggest remote archives in this case,
# the local archive must be unfolded first, and then a remote archive must be
# searched for each extracted archive. The heuristic to detect such sources
# currently is (1) there is only one archive among all Sources, (2) this
# archive contains "blob" keyword and/or ends with ".tar".
Source0:        testrpm-blob-0.1.tar

# Random file in the Sources; currently such non-archive files are ignored by
# the tool. The bogus index "1234" is just to test parsing of Source stanzas.
Source1234:     some-license.pdf

BuildArch:      noarch

%description
This is a test RPM package broken/tricky Sources for testing purposes.

%prep
%autosetup

%build
# no-op

%install
mkdir -p %{buildroot}%{_bindir}
touch %{buildroot}%{_bindir}/testrpm_for_suggesting

%files
%{_bindir}/testrpm_for_suggesting

%changelog
* Wed Oct 01 2024 Your Name <your.email@testrpmexample.com> - 0.1-1
- Initial package

